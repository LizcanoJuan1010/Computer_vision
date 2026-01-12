from fastapi import APIRouter, HTTPException, Response
from fastapi.responses import StreamingResponse
import httpx
import logging
import cv2
import asyncio
import time
from app.core.database import AsyncSessionLocal
from sqlalchemy import text

router = APIRouter()
logger = logging.getLogger("router.streaming")

async def get_camera_rtsp_url(camera_id: str):
    """Fetch RTSP URL from DB"""
    try:
        async with AsyncSessionLocal() as session:
            # Check for PostgreSQL vs others syntax if needed, assuming standard SQL
            result = await session.execute(text("SELECT rtsp_url FROM cameras WHERE id = :id"), {"id": camera_id})
            row = result.fetchone()
            if row:
                return row[0]
    except Exception as e:
        logger.error(f"DB Error fetching RTSP for {camera_id}: {e}")
    return None

async def rtsp_mjpeg_generator(rtsp_url: str):
    """
    Connect to RTSP and yield MJPEG frames.
    Note: OpenCV in a highly concurrent async environment (FastAPI) isn't ideal for large scale,
    but for a single user viewing "direct video", it works.
    """
    # ROBUST IMPLEMENTATION: Use FFmpeg subprocess to transcode RTSP -> MJPEG
    # This isolates the decoding crash from the Python process.
    import subprocess
    import sys
    
    # FFmpeg command:
    # -rtsp_transport tcp: Force TCP to avoid packet loss
    # -i rtsp_url: Input
    # -f mjpeg: Output format
    # -q:v 5: Quality (2-31, lower is better)
    # -an: No audio
    # -: Output to stdout
    command = [
        'ffmpeg',
        '-rtsp_transport', 'tcp',
        '-i', rtsp_url,
        '-f', 'mjpeg',
        '-q:v', '5',
        '-an',
        '-'
    ]
    
    logger.info(f"Starting FFmpeg with command: {' '.join(command)}")
    
    process = None
    try:
        # Start FFmpeg process
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, # Hide logs to keep console clean, or usage PIPE for debug
            bufsize=10**5 # Large buffer
        )
        
        # Generator to read MJPEG chunks
        # This is strictly a simple stream reader. MJPEG is concatenated JPEGs.
        # We need to find the JPEG boundaries (0xFFD8 start, 0xFFD9 end).
        # OR simply chunk it if the client can handle the stream (most browsers can handle mjpeg stream directly)
        # But requests usually expects --boundary. 
        # Standard FFmpeg mjpeg output IS a stream of JPEGs.
        # We need to wrap it in Multipart boundary.
        
        buffer = b""
        chunk_size = 4096
        
        while True:
            # Non-blocking read would be ideal, but for now we iterate
            # Popen stdout read is blocking. We can run it in executor if needed.
            # But simple read(chunk) might block the loop.
            # Ideally we run this generation in a separate thread.
            
            # Simplified approach: Read valid JPEG markers
            # Warning: This implementation below is basic.
            
            # Use a slightly blocking read for robustness or run in thread
            data = await asyncio.to_thread(process.stdout.read, chunk_size)
            if not data:
                break
            
            buffer += data
            a = buffer.find(b'\xff\xd8')
            b = buffer.find(b'\xff\xd9')
            
            if a != -1 and b != -1:
                jpg = buffer[a:b+2]
                buffer = buffer[b+2:]
                yield (b'--frame\r\n'
                       b'Content-Type: image/jpeg\r\n\r\n' + jpg + b'\r\n')
                       
    except Exception as e:
        logger.error(f"FFmpeg Stream error: {e}")
    finally:
        if process:
            process.kill()

@router.get("/{camera_id}/raw")
async def stream_raw(camera_id: str):
    """
    Direct RTSP -> MJPEG Stream Proxy.
    Consumes the 'original' video from the camera and serves it to frontend.
    """
    rtsp_url = await get_camera_rtsp_url(camera_id)
    if not rtsp_url:
        raise HTTPException(status_code=404, detail="Camera not found or no URL")
    
    import os
    replacements = {
        '{USER}': os.getenv('HIK_USER', ''),
        '{PASS}': os.getenv('HIK_PASS', ''),
        '{IP}': os.getenv('HIK_IP', ''),
        '{PORT_RTSP}': os.getenv('PORT_RTSP', '554')
    }
    for p, v in replacements.items():
        if v and p in rtsp_url:
            rtsp_url = rtsp_url.replace(p, v) 
         
    return StreamingResponse(rtsp_mjpeg_generator(rtsp_url), media_type="multipart/x-mixed-replace; boundary=frame")

# Keep legacy routes returning 404 or redirecting if needed
@router.get("/{camera_id}")
async def stream_camera_legacy(camera_id: str):
    return await stream_raw(camera_id)



