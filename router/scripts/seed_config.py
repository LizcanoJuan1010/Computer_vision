import asyncio
import orjson
from redis import asyncio as aioredis

async def seed():
    redis = aioredis.from_url("redis://localhost:6379/0")
    
    # Config for cam_01
    # We route it to 'security' service (which is our current monolithic inference worker)
    config = {
        "services": ["security"],
        "active": True
    }
    
    await redis.set("config:camera:cam_01", orjson.dumps(config))
    print("Seeded config for cam_01 -> ['security']")
    
    await redis.close()

if __name__ == "__main__":
    asyncio.run(seed())
