import asyncio
import sys
import os
from sqlalchemy import text, inspect

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), ".")))

from app.core.database import engine

async def main():
    print("Checking database schema...")
    try:
        async with engine.connect() as conn:
            # Check for blacklist_sharing_log table
            print("Checking for table 'blacklist_sharing_log'...")
            result = await conn.execute(text(
                "SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'blacklist_sharing_log');"
            ))
            table_exists = result.scalar()
            print(f"Table 'blacklist_sharing_log' exists: {table_exists}")
            
            # Check for is_global_blacklist column in faces table
            print("Checking for column 'is_global_blacklist' in 'faces' table...")
            result = await conn.execute(text(
                "SELECT EXISTS (SELECT FROM information_schema.columns WHERE table_name = 'faces' AND column_name = 'is_global_blacklist');"
            ))
            column_exists = result.scalar()
            print(f"Column 'is_global_blacklist' exists: {column_exists}")
            
            if not table_exists or not column_exists:
                print("SCHEM_MISMATCH")
            else:
                print("SCHEMA_OK")

    except Exception as e:
        print(f"Error checking schema: {e}")

if __name__ == "__main__":
    asyncio.run(main())
