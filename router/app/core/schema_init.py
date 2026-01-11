import logging
from sqlalchemy import text
from app.core.database import engine

logger = logging.getLogger("router.schema_init")

async def verify_and_fix_schema():
    """
    Checks if critical database schema elements exist and creates them if missing.
    This acts as a self-healing mechanism for schema evolution.
    """
    logger.info("Verifying database schema...")
    try:
        async with engine.begin() as conn:
            # 1. Check/Create blacklist_sharing_log table
            result = await conn.execute(text(
                "SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'blacklist_sharing_log');"
            ))
            table_exists = result.scalar()
            
            if not table_exists:
                logger.warning("Table 'blacklist_sharing_log' MISSING. Creating it...")
                await conn.execute(text("""
                    CREATE TABLE blacklist_sharing_log (
                        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                        face_id INTEGER REFERENCES faces(id) ON DELETE CASCADE,
                        shared_by_org_id UUID REFERENCES organizations(id),
                        action VARCHAR(50),
                        timestamp TIMESTAMPTZ DEFAULT NOW()
                    );
                """))
                logger.info("Table 'blacklist_sharing_log' created successfully.")
            
            # 2. Check/Create is_global_blacklist column
            result = await conn.execute(text(
                "SELECT EXISTS (SELECT FROM information_schema.columns WHERE table_name = 'faces' AND column_name = 'is_global_blacklist');"
            ))
            column_exists = result.scalar()
            
            if not column_exists:
                logger.warning("Column 'is_global_blacklist' MISSING in 'faces' table. Adding it...")
                await conn.execute(text(
                    "ALTER TABLE faces ADD COLUMN is_global_blacklist BOOLEAN DEFAULT FALSE;"
                ))
                logger.info("Column 'is_global_blacklist' added successfully.")
                
            logger.info("Schema verification complete.")

    except Exception as e:
        logger.error(f"Critical error verifying schema: {e}")
        # We don't raise here to allow the app to try starting, 
        # but functionality might be degraded.
