import asyncio
import websockets
import json
import time

import os
CAMERA_ID = "ca216134-0af0-453b-b7e5-9bd3c6a493a0"
WS_URL = os.getenv("WS_URL", f"ws://localhost:8003/ws/debug/{CAMERA_ID}")

async def listen():
    print(f"Connecting to {WS_URL}...")
    try:
        async with websockets.connect(WS_URL) as websocket:
            print("✅ Connected!")
            
            start_time = time.time()
            msg_count = 0
            
            while True:
                try:
                    message = await asyncio.wait_for(websocket.recv(), timeout=5.0)
                    msg_count += 1
                    data = json.loads(message)
                    
                    # Validate basic structure
                    has_faces = "faces" in data
                    has_vehicles = "vehicles" in data
                    has_zones = "zones" in data
                    has_persons = "persons" in data
                    
                    print(f"📩 Msg #{msg_count}: Faces: {len(data.get('faces', []))} | Vehicles: {len(data.get('vehicles', []))} | Persons: {len(data.get('persons', []))} | Zones: {list(data.get('zones', {}).keys())}")
                    if data.get('persons'):
                         print(f"   👤 Person[0] BBox: {data['persons'][0]['bbox']}")
                    
                    # Simple validation check
                    if 'faces' in data and 'vehicles' in data and 'persons' in data:
                        print("   -> Structure OK")

                    if msg_count >= 5:
                        print("\n✅ Verification SUCCESS: Received 5 healthy messages.")
                        break
                        
                except asyncio.TimeoutError:
                    print("❌ Timeout waiting for message.")
                    break
                except Exception as e:
                    print(f"❌ Error receiving/parsing: {e}")
                    break
                
                if time.time() - start_time > 10:
                    print("TIMEOUT: 10s limit reached.")
                    break
                    
    except Exception as e:
        print(f"❌ Connection Failed: {e}")

if __name__ == "__main__":
    asyncio.run(listen())
