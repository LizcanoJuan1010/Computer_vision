import asyncio
import nats

async def test():
    print("Connecting to NATS...")
    nc = await nats.connect('nats://nats:4222')
    print("Connected!")
    
    received = []
    async def cb(msg):
        received.append(msg.subject)
        print(f'Received on {msg.subject}', flush=True)
    
    sub = await nc.subscribe('camera.debug.*', cb=cb)
    print("Subscribed to camera.debug.*")
    print("Waiting 5 seconds for messages...")
    await asyncio.sleep(5)
    await sub.unsubscribe()
    await nc.close()
    print(f'Total messages received: {len(received)}')

asyncio.run(test())
