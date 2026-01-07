import asyncio
import nats
import json

async def trigger_alarm():
    nc = await nats.connect("nats://localhost:4223")
    
    payload = {
        "camera_id": "test-cam-1",
        "camera_name": "Test Camera Entry",
        "event_type": "intrusion",
        "track_id": 123,
        "timestamp": "2025-12-27T12:00:00Z"
    }
    
    # Subject matching what notification.py subscribes to ("events.alarm")
    await nc.publish("events.alarm", json.dumps(payload).encode())
    print("Published alarm to events.alarm")
    
    await nc.drain()

if __name__ == "__main__":
    asyncio.run(trigger_alarm())
