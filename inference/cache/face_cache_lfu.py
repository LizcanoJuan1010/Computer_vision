"""
LFU (Least Frequently Used) Hybrid Cache for Face Recognition

Architecture:
- L1 Cache: In-memory numpy arrays for ultra-fast search (< 1ms)
- L2 Cache: Redis for sharing between inference workers
- Global Blacklist: Always loaded in L1 (shared across all orgs)
- Organization Data: Loaded on-demand with LFU eviction

Author: Claude Sonnet 4.5
Date: 2025-12-23
"""

import numpy as np
import time
import asyncio
import pickle
from collections import defaultdict
from typing import Dict, List, Tuple, Optional
import redis.asyncio as redis


class FaceCacheLFU:
    """
    LFU Cache híbrido para embeddings faciales de 512 dimensiones (InsightFace).

    Características:
    - L1: Memoria RAM (numpy) - búsqueda < 1ms
    - L2: Redis - compartido entre workers
    - LFU eviction con tie-break LRU
    - Blacklist global siempre en L1
    """

    def __init__(
        self,
        l1_capacity: int = 1000,
        redis_url: str = "redis://localhost:6380",
        default_threshold: float = 0.85
    ):
        """
        Inicializar caché LFU híbrido.

        Args:
            l1_capacity: Máximo de rostros en L1 cache (default 1000)
            redis_url: URL de conexión a Redis
            default_threshold: Umbral de similaridad por defecto
        """
        # L1 Cache (Memory)
        self.l1_capacity = l1_capacity
        self.l1_embeddings: Dict[str, np.ndarray] = {}  # cache_key -> embedding (512,)
        self.l1_metadata: Dict[str, dict] = {}  # cache_key -> {id, name, category, ...}
        self.l1_frequency: Dict[str, int] = defaultdict(int)  # LFU counters
        self.l1_last_used: Dict[str, float] = {}  # LRU timestamps

        # L2 Cache (Redis)
        self.redis_url = redis_url
        self.redis_client: Optional[redis.Redis] = None

        # Global Blacklist (siempre en L1 - compartida por todas las orgs)
        self.global_blacklist_embeddings: Optional[np.ndarray] = None  # Matrix (N, 512)
        self.global_blacklist_ids: List[int] = []
        self.global_blacklist_names: List[str] = []
        self.global_blacklist_org_ids: List[str] = []  # Para saber de qué org viene

        # Config
        self.default_threshold = default_threshold

        # Stats
        self.stats = {
            'l1_hits': 0,
            'l1_misses': 0,
            'l2_hits': 0,
            'l2_misses': 0,
            'evictions': 0
        }

    async def initialize(self):
        """Inicializar conexión a Redis."""
        if self.redis_client is None:
            self.redis_client = await redis.from_url(
                self.redis_url,
                decode_responses=False,
                encoding='utf-8'
            )
            print(f"✅ Redis connection established: {self.redis_url}")

    async def load_global_blacklist(self, db):
        """
        Cargar blacklist global (compartida) en L1.
        Estas son las personas marcadas como peligrosas por múltiples organizaciones.

        Args:
            db: Database connection object
        """
        query = """
            SELECT id, name, embedding, organization_id
            FROM faces
            WHERE category = 'BLACKLIST'
              AND embedding IS NOT NULL
        """

        # Execute query synchronously via thread pool
        def _fetch():
            with db.conn.cursor() as cur:
                cur.execute(query)
                return cur.fetchall()

        result = await asyncio.to_thread(_fetch)

        if result:
            embeddings = []
            ids = []
            names = []
            org_ids = []

            for row in result:
                # row is a tuple: (id, name, embedding, organization_id)
                face_id, name, embedding_data, org_id = row

                # Convert embedding (puede ser bytes, str, o list)
                if isinstance(embedding_data, bytes):
                    embedding = np.frombuffer(embedding_data, dtype=np.float32)
                elif isinstance(embedding_data, str):
                    # pgvector devuelve como string "[0.1, 0.2, ...]"
                    import json
                    embedding = np.array(json.loads(embedding_data), dtype=np.float32)
                elif isinstance(embedding_data, list):
                    embedding = np.array(embedding_data, dtype=np.float32)
                else:
                    # Ya es un array
                    embedding = np.array(embedding_data, dtype=np.float32)

                embeddings.append(embedding)
                ids.append(face_id)
                names.append(name)
                org_ids.append(str(org_id))

            self.global_blacklist_embeddings = np.array(embeddings)  # Shape: (N, 512)
            self.global_blacklist_ids = ids
            self.global_blacklist_names = names
            self.global_blacklist_org_ids = org_ids

            print(f"✅ Loaded {len(result)} global blacklist faces into L1 cache")
        else:
            print("ℹ️  No global blacklist entries found")

    async def load_organization(self, org_id: str, db):
        """
        Cargar todos los rostros de una organización en L1.
        No incluye blacklist global (ya está cargada).

        Args:
            org_id: UUID de la organización
            db: Database connection object
        """
        query = """
            SELECT id, name, category, embedding, meta_info
            FROM faces
            WHERE organization_id = %s
              AND embedding IS NOT NULL
              AND category != 'BLACKLIST' 
        """
        
        # Execute query synchronously via thread pool
        def _fetch():
            with db.conn.cursor() as cur:
                cur.execute(query, (org_id,))
                return cur.fetchall()

        result = await asyncio.to_thread(_fetch)

        loaded_count = 0
        for row in result:
            cache_key = f"{org_id}:{row['id']}"

            # Evict LFU si L1 está lleno
            if len(self.l1_embeddings) >= self.l1_capacity:
                self._evict_lfu()

            # Guardar en L1
            embedding = np.frombuffer(row['embedding'], dtype=np.float32)
            self.l1_embeddings[cache_key] = embedding
            self.l1_metadata[cache_key] = {
                'id': row['id'],
                'name': row['name'],
                'category': row['category'],
                'meta_info': row['meta_info'],
                'org_id': org_id
            }
            self.l1_frequency[cache_key] = 0
            self.l1_last_used[cache_key] = time.time()

            # Guardar en L2 (Redis) para otros workers
            await self._save_to_l2(cache_key, embedding, self.l1_metadata[cache_key])

            loaded_count += 1

        print(f"✅ Loaded {loaded_count} faces for org {org_id} into L1 cache")
        return loaded_count

    def _evict_lfu(self):
        """
        Evict Least Frequently Used item from L1.
        Tie-break: Si múltiples items tienen misma frecuencia, evict LRU.
        """
        if not self.l1_frequency:
            return

        # Encontrar key con menor frecuencia
        min_freq = min(self.l1_frequency.values())
        candidates = [k for k, v in self.l1_frequency.items() if v == min_freq]

        if len(candidates) > 1:
            # Tie-break: usar LRU (least recently used)
            victim = min(candidates, key=lambda k: self.l1_last_used.get(k, 0))
        else:
            victim = candidates[0]

        # Eliminar de L1
        del self.l1_embeddings[victim]
        del self.l1_metadata[victim]
        del self.l1_frequency[victim]
        del self.l1_last_used[victim]

        self.stats['evictions'] += 1
        print(f"⚠️  LFU evicted: {victim} (freq={min_freq})")

    async def _save_to_l2(self, cache_key: str, embedding: np.ndarray, metadata: dict):
        """
        Guardar en Redis (L2).

        Args:
            cache_key: Clave del cache (org_id:face_id)
            embedding: Vector numpy (512,)
            metadata: Dict con id, name, category, etc
        """
        if self.redis_client is None:
            return

        try:
            data = {
                'embedding': embedding.tobytes(),
                'metadata': metadata
            }
            await self.redis_client.setex(
                f"face_cache:{cache_key}",
                3600,  # TTL 1 hora
                pickle.dumps(data)
            )
        except Exception as e:
            print(f"⚠️  Failed to save to L2: {e}")

    async def _load_from_l2(self, cache_key: str) -> Optional[Tuple[np.ndarray, dict]]:
        """
        Cargar desde Redis (L2).

        Returns:
            Tuple (embedding, metadata) o None si no existe
        """
        if self.redis_client is None:
            return None

        try:
            data = await self.redis_client.get(f"face_cache:{cache_key}")
            if data:
                unpickled = pickle.loads(data)
                embedding = np.frombuffer(unpickled['embedding'], dtype=np.float32)
                self.stats['l2_hits'] += 1
                return embedding, unpickled['metadata']
        except Exception as e:
            print(f"⚠️  Failed to load from L2: {e}")

        self.stats['l2_misses'] += 1
        return None

    async def search(
        self,
        query_embedding: np.ndarray,
        org_id: str,
        threshold: Optional[float] = None,
        include_global_blacklist: bool = True
    ) -> Optional[Tuple[int, str, str, float, bool]]:
        """
        Buscar rostro por similaridad coseno.

        Orden de búsqueda:
        1. Global blacklist (si include_global_blacklist=True)
        2. Rostros de la organización (L1 o L2)

        Args:
            query_embedding: Vector numpy (512,) del rostro detectado
            org_id: UUID de la organización
            threshold: Umbral de similaridad (default: self.default_threshold)
            include_global_blacklist: Si buscar en blacklist global

        Returns:
            Tuple (face_id, name, category, similarity, is_from_global) o None
        """
        if threshold is None:
            threshold = self.default_threshold

        # 1. Buscar en blacklist global (PRIORIDAD)
        if include_global_blacklist and self.global_blacklist_embeddings is not None:
            similarities = self._cosine_similarity_batch(
                query_embedding,
                self.global_blacklist_embeddings
            )
            best_idx = np.argmax(similarities)

            if similarities[best_idx] >= threshold:
                face_id = self.global_blacklist_ids[best_idx]
                name = self.global_blacklist_names[best_idx]
                source_org = self.global_blacklist_org_ids[best_idx]

                print(f"🚨 GLOBAL BLACKLIST HIT: {name} (similarity={similarities[best_idx]:.3f}, from org {source_org})")

                return (face_id, name, 'BLACKLIST', similarities[best_idx], True)

        # 2. Buscar en organización (L1 cache)
        org_embeddings = []
        org_metadata_list = []
        org_cache_keys = []

        for cache_key, embedding in self.l1_embeddings.items():
            if cache_key.startswith(f"{org_id}:"):
                org_embeddings.append(embedding)
                org_metadata_list.append(self.l1_metadata[cache_key])
                org_cache_keys.append(cache_key)

                # Incrementar frecuencia (LFU) y actualizar timestamp (LRU)
                self.l1_frequency[cache_key] += 1
                self.l1_last_used[cache_key] = time.time()

        if org_embeddings:
            self.stats['l1_hits'] += 1

            org_embeddings_matrix = np.array(org_embeddings)  # Shape: (M, 512)
            similarities = self._cosine_similarity_batch(
                query_embedding,
                org_embeddings_matrix
            )
            best_idx = np.argmax(similarities)

            if similarities[best_idx] >= threshold:
                metadata = org_metadata_list[best_idx]
                return (
                    metadata['id'],
                    metadata['name'],
                    metadata['category'],
                    similarities[best_idx],
                    False  # No es de global blacklist
                )
        else:
            self.stats['l1_misses'] += 1

        # 3. No match encontrado
        return None

    def _cosine_similarity_batch(
        self,
        query: np.ndarray,
        embeddings: np.ndarray
    ) -> np.ndarray:
        """
        Calcular similaridad coseno vectorizada (rápido con numpy).

        Args:
            query: Vector (512,)
            embeddings: Matrix (N, 512)

        Returns:
            Array (N,) con similaridades [0.0, 1.0]
        """
        # Normalizar query
        query_norm = query / (np.linalg.norm(query) + 1e-8)

        # Normalizar embeddings
        norms = np.linalg.norm(embeddings, axis=1, keepdims=True) + 1e-8
        embeddings_norm = embeddings / norms

        # Dot product (cosine similarity)
        similarities = np.dot(embeddings_norm, query_norm)

        return similarities

    async def invalidate(self, face_id: int, org_id: str):
        """
        Invalidar caché cuando se actualiza/elimina un rostro.

        Args:
            face_id: ID del rostro
            org_id: UUID de la organización
        """
        cache_key = f"{org_id}:{face_id}"

        # Eliminar de L1
        if cache_key in self.l1_embeddings:
            del self.l1_embeddings[cache_key]
            del self.l1_metadata[cache_key]
            del self.l1_frequency[cache_key]
            del self.l1_last_used[cache_key]
            print(f"✅ Invalidated L1 cache for face {face_id} in org {org_id}")

        # Eliminar de L2 (Redis)
        if self.redis_client:
            try:
                await self.redis_client.delete(f"face_cache:{cache_key}")
                print(f"✅ Invalidated L2 cache for face {face_id}")
            except Exception as e:
                print(f"⚠️  Failed to invalidate L2: {e}")

    async def invalidate_global_blacklist(self, db):
        """
        Recargar blacklist global completamente.
        Llamar cuando alguien comparte/descomparte una entrada.
        """
        print("🔄 Reloading global blacklist...")
        await self.load_global_blacklist(db)

    def get_stats(self) -> dict:
        """Obtener estadísticas del caché."""
        total_requests = self.stats['l1_hits'] + self.stats['l1_misses']
        l1_hit_rate = (self.stats['l1_hits'] / total_requests * 100) if total_requests > 0 else 0

        return {
            **self.stats,
            'l1_size': len(self.l1_embeddings),
            'l1_capacity': self.l1_capacity,
            'l1_hit_rate_pct': round(l1_hit_rate, 2),
            'global_blacklist_size': len(self.global_blacklist_ids)
        }

    def clear_l1(self):
        """Limpiar completamente L1 cache."""
        self.l1_embeddings.clear()
        self.l1_metadata.clear()
        self.l1_frequency.clear()
        self.l1_last_used.clear()
        print("🗑️  L1 cache cleared")

    async def close(self):
        """Cerrar conexiones."""
        if self.redis_client:
            await self.redis_client.close()
            print("✅ Redis connection closed")
