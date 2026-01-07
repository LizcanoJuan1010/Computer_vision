from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from app.services.notification import manager
import logging

router = APIRouter()
logger = logging.getLogger("router.ws")

@router.websocket("/notifications")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            # Keep connection open, wait for messages (ping/pong)
            # We don't expect client to send much, mostly push from server
            data = await websocket.receive_text()
            # Echo or Ignore
            pass 
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception as e:
        logger.error(f"WebSocket Error: {e}")
        manager.disconnect(websocket)
