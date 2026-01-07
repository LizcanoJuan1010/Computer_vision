import asyncio
import logging
from fastapi import WebSocket

logger = logging.getLogger("router.ws")

class WebSocketManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []
        self.nc = None

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        logger.info(f"WebSocket client connected. Total: {len(self.active_connections)}")

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
            logger.info("WebSocket client disconnected")

    async def broadcast(self, message: str):
        for connection in self.active_connections:
            try:
                await connection.send_text(message)
            except Exception as e:
                logger.error(f"Error broadcasting to client: {e}")
                # Don't remove here, let disconnect handle it or next send fail
    
    async def start_nats_listener(self, nc):
        """Standard NATS listener for events.alarm"""
        self.nc = nc
        
        async def cb(msg):
            data = msg.data.decode()
            # Wrap as JSON event for Frontend
            # msg.data is already JSON from security.py
            # we might want to wrap it: {"type": "ALARM_TRIGGERED", "data": ...}
            import json
            try:
                payload = json.loads(data)
                event = {
                    "type": "ALARM_TRIGGERED",
                    "data": payload
                }
                await self.broadcast(json.dumps(event))
            except Exception as e:
                logger.error(f"Error processing alarm msg: {e}")

        await nc.subscribe("events.alarm", cb=cb)
        logger.info("Subscribed to events.alarm")

manager = WebSocketManager()
