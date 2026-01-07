import logging
import nats
from nats.aio.client import Client as NATSClient

from app.core.config import settings
from app.services.cache import router_cache
from app.services.multitenancy_utils import parse_nats_subject

logger = logging.getLogger("router.dispatcher")

class Dispatcher:
    """
    Handles the core routing logic:
    Frame -> Extract ID -> Cache Lookup -> Fan-Out Publish
    """
    def __init__(self, nc: NATSClient):
        self.nc = nc

    async def process_frame(self, msg):
        """
        Core Routing Logic (Multi-Tenancy Aware).
        CRITICAL: This function must be non-blocking and extremely fast.

        Supports both:
        - New format: org.{org}.zone.{zone}.camera.{id}.frame
        - Legacy format: camera.{id}.frame
        """
        try:
            # 1. Parse Subject (Supports Multi-Tenancy + Legacy)
            subject = msg.subject
            subject_info = parse_nats_subject(subject)

            camera_id = subject_info["camera_id"]
            org_slug = subject_info["org_slug"]
            zone_slug = subject_info["zone_slug"]
            is_legacy = subject_info["is_legacy"]

            # 2. Routing Decision (O(1) Lookup with Multi-Tenancy Context)
            # This hits L1 Cache (Memory) 99% of the time -> Sub-microsecond latency
            target_services = await router_cache.get_services(
                camera_id=camera_id,
                org_slug=org_slug,
                zone_slug=zone_slug
            )

            # 3. Fan-Out (Dispatch)
            # We publish the RAW payload (msg.data) directly.
            # No decoding, no processing. Pure pass-through.
            for service in target_services:
                target_subject = f"work.{service}"

                # Publish Async (Fire and Forget)
                # Preserve original headers + add multi-tenancy metadata
                headers = msg.header or {}
                headers["camera_id"] = camera_id

                # Add multi-tenancy context if available
                if org_slug:
                    headers["org_slug"] = org_slug
                if zone_slug:
                    headers["zone_slug"] = zone_slug
                headers["is_legacy"] = str(is_legacy)  # Convert bool to string for NATS headers

                await self.nc.publish(target_subject, msg.data, headers=headers)

        except Exception as e:
            logger.error(f"Error routing frame from subject '{msg.subject}': {e}")
