import asyncio
import sys
import os

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.core.database import engine, get_db
from app.models import User, Role

async def main():
    print("Testing model imports...")
    try:
        u = User(username="test", email="test@example.com", password_hash="hash")
        r = Role(code="ADMIN", name="Administrator")
        print("Models imported successfully.")
    except Exception as e:
        print(f"Model import failed: {e}")
        return

    print("Testing connection (expect failure if DB not running)...")
    try:
        async with engine.begin() as conn:
            await conn.run_sync(User.metadata.create_all)
        print("Connection successful!")
    except Exception as e:
        print(f"Connection failed as expected if DB is down: {e}")

if __name__ == "__main__":
    asyncio.run(main())
