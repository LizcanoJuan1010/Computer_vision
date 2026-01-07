from fastapi import APIRouter, HTTPException, Response
from fastapi.responses import StreamingResponse
import httpx
import logging

router = APIRouter()
logger = logging.getLogger("router.streaming")

INGEST_URL = "http://vision-ingest:8080"
INFERENCE_URL = "http://vision-inference:5000"

async def proxy_stream_request(url: str):
    """
    Helper to proxy a stream (MJPEG) from an upstream URL.
    """
    async def iter_stream():
        try:
            async with httpx.AsyncClient() as client:
                async with client.stream("GET", url, timeout=None) as resp:
                    if resp.status_code != 200:
                         yield b""
                         return
                    async for chunk in resp.aiter_bytes():
                        yield chunk
        except Exception as e:
            logger.error(f"Stream proxy error for {url}: {e}")
            pass

    return StreamingResponse(iter_stream(), media_type="multipart/x-mixed-replace; boundary=frame")


@router.post("/test-connection")
async def test_connection(data: dict):
    """
    Proxy test-connection request to Inference Service.
    """
    url = f"{INFERENCE_URL}/test-rtsp"
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(url, json=data, timeout=5.0)
            return Response(content=resp.content, status_code=resp.status_code, media_type="application/json")
    except Exception as e:
        logger.error(f"Test connection error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
@router.get("/snapshot/{camera_id}")
async def get_snapshot(camera_id: str):
    """Proxy snapshot from Ingest service"""
    url = f"{INGEST_URL}/snapshot/{camera_id}"
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(url, timeout=2.0)
            if resp.status_code != 200:
                raise HTTPException(status_code=resp.status_code, detail="Snapshot not available")
            return Response(content=resp.content, media_type="image/jpeg")
    except httpx.ConnectError:
        raise HTTPException(status_code=503, detail="Ingest service unavailable")
    except Exception as e:
        logger.error(f"Snapshot error: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@router.get("/{camera_id}")
async def stream_camera(camera_id: str):
    """Proxy MJPEG stream from Ingest service (Raw Video) - Default endpoint"""
    url = f"{INGEST_URL}/stream/{camera_id}"
    return await proxy_stream_request(url)

@router.get("/{camera_id}/mjpeg")
async def stream_mjpeg(camera_id: str):
    """Proxy MJPEG stream from Ingest service (Raw Video)"""
    url = f"{INGEST_URL}/stream/{camera_id}"
    return await proxy_stream_request(url)

@router.get("/annotate/{camera_id}")
async def get_annotated_stream(camera_id: str):
    """
    Proxy the annotated MJPEG stream from the Inference Service (running on host).
    """
    url = f"{INFERENCE_URL}/debug/{camera_id}/mjpeg"
    return await proxy_stream_request(url)


