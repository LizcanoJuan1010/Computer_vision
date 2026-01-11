import asyncio
import sys
import os
from sqlalchemy import text

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.core.database import engine

async def main():
    print("Checking database schema...")
    try:
        async with engine.begin() as conn:
            # 1. Check/Create blacklist_sharing_log table
            print("Checking for table 'blacklist_sharing_log'...")
            result = await conn.execute(text(
                "SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'blacklist_sharing_log');"
            ))
            table_exists = result.scalar()
            
            if not table_exists:
                print("Table 'blacklist_sharing_log' MISSING. Creating it...")
                await conn.execute(text("""
                    CREATE TABLE blacklist_sharing_log (
                        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                        face_id INTEGER REFERENCES faces(id) ON DELETE CASCADE,
                        shared_by_org_id UUID REFERENCES organizations(id),
                        action VARCHAR(50),
                        timestamp TIMESTAMPTZ DEFAULT NOW()
                    );
                """))
                print("Table 'blacklist_sharing_log' created.")
            else:
                print("Table 'blacklist_sharing_log' exists.")

            # 2. Check/Create is_global_blacklist column
            print("Checking for column 'is_global_blacklist' in 'faces' table...")
            result = await conn.execute(text(
                "SELECT EXISTS (SELECT FROM information_schema.columns WHERE table_name = 'faces' AND column_name = 'is_global_blacklist');"
            ))
            column_exists = result.scalar()
            
            if not column_exists:
                print("Column 'is_global_blacklist' MISSING. Adding it...")
                await conn.execute(text(
                    "ALTER TABLE faces ADD COLUMN is_global_blacklist BOOLEAN DEFAULT FALSE;"
                ))
                print("Column 'is_global_blacklist' added.")
            else:
                print("Column 'is_global_blacklist' exists.")
                
            print("Schema verification and repair complete.")

    except Exception as e:
        print(f"Error checking/fixing schema: {e}")

if __name__ == "__main__":
    asyncio.run(main())
