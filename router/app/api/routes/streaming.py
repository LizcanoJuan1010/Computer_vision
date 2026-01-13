from fastapi import APIRouter, HTTPException, Response
from fastapi.responses import RedirectResponse
import httpx
import logging
import os
import time
from app.core.database import AsyncSessionLocal
from sqlalchemy import text

router = APIRouter()
logger = logging.getLogger("router.streaming")

# MediaMTX Config
MEDIAMTX_API = os.getenv("MEDIAMTX_API", "http://mediamtx:9997/v3/config/paths")
MEDIAMTX_WEBRTC_HOST = "http://localhost:8889" # Address accessible by Browser

class MediaMTXClient:
    """Helper to interact with MediaMTX API"""
    
    @staticmethod
    async def ensure_path(camera_id: str, rtsp_url: str):
        """
        Check if path exists in MediaMTX. If not, create it.
        Path name will be the camera_id.
        """
        path_name = camera_id
        
        async with httpx.AsyncClient() as client:
            try:
                # 1. Check if exists (GET /paths/get/{name})
                # MediaMTX v1.1+ API: GET /v3/paths/get/{name}
                # Check config or runtime? 
                # Managing 'paths' in config (POST /v3/config/paths/add/{name})
                
                # Let's try to add it. If it exists, it might update or error.
                # Simplest for now: POST /v3/config/paths/add/{name}
                
                payload = {
                    "source": rtsp_url,
                    "sourceOnDemand": False # Force connection for debugging
                }
                
                resp = await client.post(f"{MEDIAMTX_API}/add/{path_name}", json=payload)
                
                if resp.status_code == 200:
                    logger.info(f"✅ MediaMTX: Added path {path_name}")
                elif resp.status_code == 400 and "already exists" in resp.text:
                    # Perform update if needed, but for now assume it's fine
                    # logger.info(f"ℹ️ MediaMTX: Path {path_name} already exists. Updating...")
                    # Update logic: POST /v3/config/paths/replace/{name}
                    await client.post(f"{MEDIAMTX_API}/replace/{path_name}", json=payload)
                else:
                    logger.warning(f"⚠️ MediaMTX Check: {resp.status_code} - {resp.text}")

            except Exception as e:
                logger.error(f"❌ MediaMTX API Error: {e}")

async def get_camera_rtsp_url(camera_id: str):
    """Fetch RTSP URL from DB and inject credentials"""
    try:
        async with AsyncSessionLocal() as session:
            result = await session.execute(text("SELECT rtsp_url FROM cameras WHERE id = :id"), {"id": camera_id})
            row = result.fetchone()
            if row:
                rtsp_url = row[0]
                replacements = {
                    '{USER}': os.getenv('HIK_USER', ''),
                    '{PASS}': os.getenv('HIK_PASS', ''),
                    '{IP}': os.getenv('HIK_IP', ''),
                    '{PORT_RTSP}': os.getenv('PORT_RTSP', '554')
                }
                for p, v in replacements.items():
                    if v and p in rtsp_url:
                        rtsp_url = rtsp_url.replace(p, v)
                return rtsp_url
    except Exception as e:
        logger.error(f"DB Error fetching RTSP for {camera_id}: {e}")
    return None

@router.get("/{camera_id}/raw")
@router.get("/{camera_id}")
async def stream_raw(camera_id: str):
    """
    Redirects to MediaMTX WebRTC player.
    """
    # 1. Get RTSP URL
    rtsp_url = await get_camera_rtsp_url(camera_id)
    if not rtsp_url:
        raise HTTPException(status_code=404, detail="Camera not found or no URL")
            # Ingest Service is now Pushing to MediaMTX directly.
            # We do NOT need to configure the path here. 
            # If we do, we might conflict with the active push.
            # await MediaMTXClient.ensure_path(camera_id, rtsp_url)
            
            # Construct MediaMTX WebRTC URL
            # Format: http://<mediamtx_host>:8889/<path_name>/
            # Note: The path name in MediaMTX will be the camera_id
    mediamtx_webrtc_url = f"{MEDIAMTX_WEBRTC_HOST}/{camera_id}/"
    
    return RedirectResponse(url=mediamtx_webrtc_url)
    # If the frontend uses <img src> (which expects image data), a redirect to an HTML page won't work.
    # This requires Frontend Change.



