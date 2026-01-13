import asyncio
import websockets

async def test_ws():
    uri = "ws://localhost:8003/ws/debug/ee7433b9-d6e1-41f2-bc92-ae931e884d4c"
    print(f"Connecting to: {uri}")
    try:
        async with websockets.connect(uri) as websocket:
            print("✅ Connected!")
            # Send ping
            await websocket.send("ping")
            response = await asyncio.wait_for(websocket.recv(), timeout=5.0)
            print(f"Response: {response}")
    except Exception as e:
        print(f"❌ Error: {e}")

asyncio.run(test_ws())
