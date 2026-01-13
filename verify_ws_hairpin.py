import asyncio
import websockets
import json

async def test_ws():
    # Attempt to connect via the HOST Loopback (simulating external access)
    uri = "ws://host.docker.internal:8003/ws/debug/test-cam"
    print(f"Connecting to {uri}...")
    try:
        async with websockets.connect(uri) as websocket:
            print("✅ Connected via Host Loopback!")
            await websocket.send("ping")
            response = await websocket.recv()
            print(f"📩 Received: {response}")
    except Exception as e:
        print(f"❌ Host Loopback Failed: {e}")

if __name__ == "__main__":
    asyncio.run(test_ws())
