# Database Setup

This directory contains the schema and initialization scripts for the VIGIAS-IA PostgreSQL database.

## Schema

The schema is defined in `schema.sql`. It includes:
- **RBAC**: Users, Roles, Permissions.
- **Infrastructure**: Cameras, AI Configs.
- **Events**: Alarms, Actions.
- **Audit**: Logs.

## Initialization

To initialize the database, ensure the PostgreSQL container is running.

```bash
# Check if container is running
docker ps

# Initialize DB (default port 5436)
python3 database/init_db.py

# If using a different port (e.g. 5435)
DB_PORT=5435 python3 database/init_db.py
```

## Models

SQLAlchemy models are located in `router/app/models.py`.
The application is configured to connect via `router/app/core/config.py`.
