import logging
import json
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from app.core.config import settings

router = APIRouter()
logger = logging.getLogger("router.debug")

import asyncio

@router.websocket("/{camera_id}")
async def debug_websocket(websocket: WebSocket, camera_id: str):
    print(f"DEBUG: Handling WS request for {camera_id}", flush=True)
    await websocket.accept()
    logger.info(f"Debug WS connected for {camera_id}")
    
    # We need access to the global NATS connection
    # It's stored in app.state.nc
    nc = websocket.app.state.nc
    subscription = None
    
    try:
        if not nc:
            await websocket.close(code=1011, reason="NATS not available")
            return

        async def cb(msg):
            try:
                # Forward directly
                await websocket.send_text(msg.data.decode())
            except Exception as e:
                logger.error(f"Error sending to WS: {e}")

        subject = f"camera.debug.{camera_id}"
        subscription = await nc.subscribe(subject, cb=cb)
        logger.info(f"Subscribed to {subject}")
        
        while True:
            # Keep alive and receive control messages if any
            # Use timeout to prevent blocking the event loop indefinitely
            try:
                 data = await asyncio.wait_for(websocket.receive_text(), timeout=1.0)
                 if data == "ping":
                     await websocket.send_text("pong")
            except asyncio.TimeoutError:
                 continue

            
    except WebSocketDisconnect:
        logger.info(f"Debug WS disconnected for {camera_id}")
    except Exception as e:
        logger.error(f"Debug WS Error: {e}")
    finally:
        if subscription:
            await subscription.unsubscribe()
