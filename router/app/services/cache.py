import orjson
import logging
from redis import asyncio as aioredis
from cachetools import TTLCache
from typing import List, Set, Optional

from app.core.config import settings
from app.services.multitenancy_utils import build_redis_cache_key

logger = logging.getLogger("router.cache")

class TieredCache:
    """
    High-Performance Tiered Cache (L1: Memory, L2: Redis).
    Optimized for Read-Heavy workloads (Routing).
    """
    def __init__(self):
        # L1 Cache: Memory (TTLCache)
        # Access time: ~100ns
        # Uses LRU eviction policy if full.
        self.l1 = TTLCache(maxsize=settings.L1_MAXSIZE, ttl=settings.L1_TTL)
        
        # L2 Cache: Redis
        # Access time: ~1-2ms
        self.redis: Optional[aioredis.Redis] = None

    async def connect(self):
        """Initializes Redis connection pool."""
        self.redis = aioredis.from_url(
            f"redis://{settings.REDIS_HOST}:{settings.REDIS_PORT}/{settings.REDIS_DB}",
            encoding="utf-8",
            decode_responses=True
        )
        logger.info(f"Connected to Redis at {settings.REDIS_HOST}:{settings.REDIS_PORT}")

    async def close(self):
        if self.redis:
            await self.redis.close()

    async def get_services(
        self,
        camera_id: str,
        org_slug: Optional[str] = None,
        zone_slug: Optional[str] = None
    ) -> Set[str]:
        """
        Returns the set of active services for a camera.
        Complexity: O(1) due to L1 Cache and Set lookups.

        Args:
            camera_id: Camera identifier
            org_slug: Organization slug (optional, for multi-tenancy)
            zone_slug: Zone slug (optional, for multi-tenancy)

        Returns:
            Set of active service names
        """
        # Build cache key (supports both new and legacy format)
        cache_key = f"{org_slug}:{zone_slug}:{camera_id}" if org_slug and zone_slug else camera_id

        # 1. Try L1 Cache (Zero Network I/O)
        if cache_key in self.l1:
            return self.l1[cache_key]

        # 2. Try L2 Cache (Redis)
        if self.redis:
            try:
                # Build Redis key with multi-tenancy support
                redis_key = build_redis_cache_key(camera_id, org_slug, zone_slug)
                data = await self.redis.get(redis_key)

                if data:
                    # Parse JSON using orjson (Rust-based, ultra fast)
                    config = orjson.loads(data)

                    # Optimization: Convert list to Set for O(1) membership tests later
                    services = set(config.get("services", []))

                    # Populate L1
                    self.l1[cache_key] = services
                    return services
            except Exception as e:
                logger.error(f"Redis error: {e}")

        # 3. Fallback / Default
        # If not found or error, return default services (e.g., just YOLO)
        # or empty set if we want to be strict.
        # For now, let's assume every camera gets 'security' by default for safety.
        default_services = {"security"}
        self.l1[cache_key] = default_services
        return default_services

    async def invalidate(
        self,
        camera_id: str,
        org_slug: Optional[str] = None,
        zone_slug: Optional[str] = None
    ):
        """
        Purges L1 cache for a specific camera.

        Args:
            camera_id: Camera identifier
            org_slug: Organization slug (optional, for multi-tenancy)
            zone_slug: Zone slug (optional, for multi-tenancy)
        """
        # Build cache key (supports both new and legacy format)
        cache_key = f"{org_slug}:{zone_slug}:{camera_id}" if org_slug and zone_slug else camera_id

        if cache_key in self.l1:
            del self.l1[cache_key]
            logger.debug(f"Invalidated L1 for {cache_key}")

    async def set_config(
        self,
        camera_id: str,
        services: List[str],
        org_slug: Optional[str] = None,
        zone_slug: Optional[str] = None
    ):
        """
        Updates L2 and invalidates L1 (Write-Through / Invalidate).

        Args:
            camera_id: Camera identifier
            services: List of active services
            org_slug: Organization slug (optional, for multi-tenancy)
            zone_slug: Zone slug (optional, for multi-tenancy)
        """
        if self.redis:
            # Build Redis key with multi-tenancy support
            redis_key = build_redis_cache_key(camera_id, org_slug, zone_slug)

            payload = orjson.dumps({"services": services, "active": True})
            await self.redis.set(redis_key, payload)

            # Invalidate L1 so next read fetches fresh data
            await self.invalidate(camera_id, org_slug, zone_slug)

router_cache = TieredCache()
