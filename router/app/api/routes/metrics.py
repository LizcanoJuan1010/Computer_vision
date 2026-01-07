"""
Prometheus Metrics Endpoint

Exposes metrics for Prometheus scraping.
"""
from fastapi import APIRouter
from fastapi.responses import Response

from app.core.metrics import get_metrics_response

router = APIRouter()


@router.get("/metrics")
async def metrics():
    """
    Prometheus metrics endpoint.

    This endpoint is scraped by Prometheus to collect metrics.

    Configure Prometheus with:
    ```yaml
    scrape_configs:
      - job_name: 'vigias-router'
        static_configs:
          - targets: ['localhost:8003']
        metrics_path: '/metrics'
        scrape_interval: 15s
    ```

    **Response:** Prometheus text format metrics
    """
    return get_metrics_response()
