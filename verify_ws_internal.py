import asyncio
import websockets
import json

async def test_ws():
    # Connect to Router service by hostname (internal Docker network)
    uri = "ws://router:8000/ws/debug/ee7433b9-d6e1-41f2-bc92-ae931e884d4c"
    print(f"Connecting to {uri}...")
    try:
        async with websockets.connect(uri) as websocket:
            print("✅ Connected to Router Internal WS!")
            await websocket.send("ping")
            print("✅ Sent Ping")
            
            # Wait for data (metadata from inference)
            response = await asyncio.wait_for(websocket.recv(), timeout=10.0)
            print(f"📩 Received Data: {response[:100]}...")
    except Exception as e:
        print(f"❌ Internal Connection Failed: {e}")

if __name__ == "__main__":
    asyncio.run(test_ws())
