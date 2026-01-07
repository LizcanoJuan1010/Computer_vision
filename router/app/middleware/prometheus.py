"""
Prometheus Middleware for automatic request tracking.

Tracks all HTTP requests with method, endpoint, status code, and duration.
"""
import time
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from app.core.metrics import track_request


class PrometheusMiddleware(BaseHTTPMiddleware):
    """
    Middleware that automatically tracks all API requests in Prometheus.
    """

    async def dispatch(self, request: Request, call_next):
        # Skip metrics endpoint to avoid recursion
        if request.url.path == "/metrics":
            return await call_next(request)

        # Track start time
        start_time = time.time()

        # Process request
        response: Response = await call_next(request)

        # Calculate duration
        duration = time.time() - start_time

        # Extract endpoint pattern (remove IDs for better aggregation)
        endpoint = self._normalize_path(request.url.path)

        # Track metrics
        track_request(
            method=request.method,
            endpoint=endpoint,
            status_code=response.status_code,
            duration=duration
        )

        return response

    def _normalize_path(self, path: str) -> str:
        """
        Normalize path by replacing UUIDs and IDs with placeholders.

        Examples:
        - /api/v1/cameras/123e4567-e89b-12d3-a456-426614174000 -> /api/v1/cameras/{id}
        - /api/v1/orgs/acme/zones/warehouse/cameras -> /api/v1/orgs/{org}/zones/{zone}/cameras
        """
        import re

        # Replace UUIDs
        path = re.sub(
            r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}',
            '{id}',
            path,
            flags=re.IGNORECASE
        )

        # Replace numeric IDs
        path = re.sub(r'/\d+(?:/|$)', '/{id}/', path)

        # Replace organization slugs
        path = re.sub(r'/orgs/[a-z0-9_-]+/', '/orgs/{org}/', path)

        # Replace zone slugs
        path = re.sub(r'/zones/[a-z0-9_-]+/', '/zones/{zone}/', path)

        # Clean up any double slashes
        path = re.sub(r'/+', '/', path)

        return path.rstrip('/')
