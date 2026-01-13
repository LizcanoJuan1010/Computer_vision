import asyncio
import websockets

async def test_ws():
    uri = ws://localhost:8003/ws/debug/ee7433b9-d6e1-41f2-bc92-ae931e884d4c"
    print(f"Testing WebSocket: {uri}")
    try:
        async with websockets.connect(uri, timeout=5) as ws:
            print("✅ Connected!")
            await ws.send("ping")
            response = await asyncio.wait_for(ws.recv(), timeout=3)
            print(f"Response: {response}")
    except Exception as e:
        print(f"❌ Error: {type(e).__name__}: {e}")

asyncio.run(test_ws())
