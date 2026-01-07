#!/usr/bin/env python3
"""
SCRIPT DE MIGRACIÓN A UUIDs - VIGIAS-IA

Este script ejecuta la migración completa de la base de datos a UUIDs.

Uso:
    python3 run_migration.py

Prerrequisitos:
    - Docker postgres container corriendo
    - Backup ya creado (backup_before_uuid_migration_*.sql)
"""

import os
import sys
import psycopg2
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT
import time

# Configuración
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", "5436")
DB_USER = os.getenv("DB_USER", "user")
DB_PASSWORD = os.getenv("DB_PASSWORD", "password")
DB_NAME = os.getenv("DB_NAME", "vigias")

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SCHEMA_FILE = os.path.join(SCRIPT_DIR, "schema.sql")
MIGRATION_FILE = os.path.join(SCRIPT_DIR, "migrate_to_uuid.sql")

def print_header(text):
    print("\n" + "="*70)
    print(f"  {text}")
    print("="*70)

def execute_sql_file(cursor, filepath, description):
    """Ejecuta un archivo SQL completo."""
    print(f"\n📄 Ejecutando: {description}")
    print(f"   Archivo: {os.path.basename(filepath)}")

    with open(filepath, 'r') as f:
        sql = f.read()

    try:
        cursor.execute(sql)
        print("   ✅ Completado")
        return True
    except Exception as e:
        print(f"   ❌ Error: {e}")
        return False

def verify_counts(cursor):
    """Verifica que los conteos coincidan."""
    print("\n📊 Verificando conteos...")

    tables = ['cameras', 'events', 'camera_stats']

    for table in tables:
        try:
            # Contar tabla vieja
            cursor.execute(f"SELECT COUNT(*) FROM {table}_old")
            old_count = cursor.fetchone()[0]

            # Contar tabla nueva
            cursor.execute(f"SELECT COUNT(*) FROM {table}")
            new_count = cursor.fetchone()[0]

            status = "✅" if old_count == new_count else "❌"
            print(f"   {status} {table}: {old_count} -> {new_count}")

        except Exception as e:
            print(f"   ⚠️  {table}: Error al verificar - {e}")

def show_sample_data(cursor):
    """Muestra datos de ejemplo para verificación manual."""
    print("\n🔍 Muestra de datos migrados:")

    print("\n   CAMERAS:")
    cursor.execute("SELECT id, name, is_active FROM cameras LIMIT 3")
    for row in cursor.fetchall():
        print(f"   - {row[0]} | {row[1]} | Active: {row[2]}")

    print("\n   EVENTS (últimos 3):")
    cursor.execute("""
        SELECT e.id, c.name, e.event_type, e.severity
        FROM events e
        LEFT JOIN cameras c ON e.camera_id = c.id
        ORDER BY e.occurred_at DESC
        LIMIT 3
    """)
    for row in cursor.fetchall():
        print(f"   - {row[0]} | Cam: {row[1]} | {row[2]} | {row[3]}")

def main():
    print_header("🚀 MIGRACIÓN A UUIDs - VIGIAS-IA DATABASE")

    # Confirmar con el usuario
    print("\n⚠️  ADVERTENCIA:")
    print("   Este script modificará la estructura de la base de datos.")
    print("   Asegúrate de que:")
    print("   1. Existe un backup reciente (backup_before_uuid_migration_*.sql)")
    print("   2. No hay servicios corriendo que usen la DB")
    print("   3. Tienes tiempo para completar la migración (~2-5 min)")

    response = input("\n¿Continuar con la migración? (yes/no): ")
    if response.lower() != 'yes':
        print("❌ Migración cancelada por el usuario.")
        sys.exit(0)

    # Conectar a la base de datos
    print_header("1️⃣  CONECTANDO A LA BASE DE DATOS")

    try:
        conn = psycopg2.connect(
            dbname=DB_NAME,
            user=DB_USER,
            password=DB_PASSWORD,
            host=DB_HOST,
            port=DB_PORT
        )
        conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
        cur = conn.cursor()
        print(f"✅ Conectado a {DB_NAME}@{DB_HOST}:{DB_PORT}")
    except Exception as e:
        print(f"❌ Error de conexión: {e}")
        sys.exit(1)

    # Paso 1: Renombrar tablas existentes
    print_header("2️⃣  RENOMBRANDO TABLAS EXISTENTES")

    try:
        cur.execute("ALTER TABLE IF EXISTS cameras RENAME TO cameras_old")
        cur.execute("ALTER TABLE IF EXISTS events RENAME TO events_old")
        cur.execute("ALTER TABLE IF EXISTS faces RENAME TO faces_old")
        cur.execute("ALTER TABLE IF EXISTS camera_stats RENAME TO camera_stats_old")
        print("✅ Tablas renombradas a *_old")
    except Exception as e:
        print(f"❌ Error renombrando tablas: {e}")
        sys.exit(1)

    # Paso 2: Ejecutar schema.sql
    print_header("3️⃣  EJECUTANDO SCHEMA.SQL (creando tablas nuevas con UUIDs)")

    if not execute_sql_file(cur, SCHEMA_FILE, "Schema completo con UUIDs"):
        print("\n❌ Error ejecutando schema.sql")
        print("   Puedes restaurar el backup con:")
        print(f"   docker exec -i postgres psql -U {DB_USER} {DB_NAME} < backup_before_uuid_migration_*.sql")
        sys.exit(1)

    # Paso 3: Migrar datos
    print_header("4️⃣  MIGRANDO DATOS DE TABLAS ANTIGUAS A NUEVAS")

    # Crear extensión pgvector si no existe
    try:
        cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
        print("✅ Extensión pgvector verificada")
    except Exception as e:
        print(f"⚠️  Advertencia pgvector: {e}")

    # Crear tabla de mapeo temporal
    cur.execute("""
        CREATE TEMPORARY TABLE id_mapping (
            old_camera_id INTEGER,
            new_camera_id UUID
        )
    """)

    # Migrar CAMERAS
    print("\n📦 Migrando cameras...")
    cur.execute("""
        INSERT INTO cameras (id, name, rtsp_url, location_name, meta_info, is_active, created_at, updated_at)
        SELECT
            gen_random_uuid() as id,
            name,
            rtsp_url,
            location_name,
            COALESCE(meta_info, '{}'::jsonb),
            COALESCE(is_active, true),
            COALESCE(created_at, NOW()),
            COALESCE(updated_at, NOW())
        FROM cameras_old
    """)
    cameras_migrated = cur.rowcount
    print(f"   ✅ {cameras_migrated} cámaras migradas")

    # Crear mapeo de IDs
    cur.execute("""
        INSERT INTO id_mapping (old_camera_id, new_camera_id)
        SELECT co.id, c.id
        FROM cameras_old co
        JOIN cameras c ON c.name = co.name
    """)

    # Migrar EVENTS
    print("\n📦 Migrando events...")
    cur.execute("""
        INSERT INTO events (
            id, camera_id, config_id, event_type, track_id, confidence,
            snapshot_path, video_clip_path, bbox, severity, status,
            created_at, occurred_at
        )
        SELECT
            gen_random_uuid() as id,
            im.new_camera_id,
            NULL as config_id,
            eo.event_type,
            eo.track_id,
            eo.confidence,
            eo.snapshot_path,
            eo.video_clip_path,
            eo.bbox,
            COALESCE(eo.severity, 'MEDIUM')::event_severity_enum,
            COALESCE(eo.status, 'PENDING')::event_status_enum,
            COALESCE(eo.created_at, NOW()),
            COALESCE(eo.occurred_at, NOW())
        FROM events_old eo
        LEFT JOIN id_mapping im ON eo.camera_id = im.old_camera_id
    """)
    events_migrated = cur.rowcount
    print(f"   ✅ {events_migrated} eventos migrados")

    # Migrar FACES (mantener SERIAL por compatibilidad con pgvector)
    print("\n📦 Migrando faces...")
    cur.execute("""
        DROP TABLE IF EXISTS faces;
        CREATE TABLE faces (
            id SERIAL PRIMARY KEY,
            name VARCHAR(100),
            embedding vector(512),
            created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
        )
    """)

    # Verificar si hay datos en faces_old
    cur.execute("SELECT COUNT(*) FROM faces_old")
    faces_count = cur.fetchone()[0]

    if faces_count > 0:
        cur.execute("""
            INSERT INTO faces (name, embedding, created_at)
            SELECT name, embedding, created_at
            FROM faces_old
        """)
        print(f"   ✅ {faces_count} rostros migrados")
    else:
        print(f"   ℹ️  No hay rostros para migrar")

    # Migrar CAMERA_STATS
    print("\n📦 Migrando camera_stats...")
    cur.execute("""
        DROP TABLE IF EXISTS camera_stats;
        CREATE TABLE camera_stats (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            camera_id UUID REFERENCES cameras(id) ON DELETE CASCADE,
            timestamp TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
            in_count INTEGER,
            out_count INTEGER
        )
    """)

    cur.execute("""
        INSERT INTO camera_stats (id, camera_id, timestamp, in_count, out_count)
        SELECT
            gen_random_uuid(),
            c.id,
            cs.timestamp,
            cs.in_count,
            cs.out_count
        FROM camera_stats_old cs
        LEFT JOIN cameras c ON c.name = cs.camera_id
    """)
    stats_migrated = cur.rowcount
    print(f"   ✅ {stats_migrated} registros de stats migrados")

    # Verificación
    print_header("5️⃣  VERIFICACIÓN")
    verify_counts(cur)
    show_sample_data(cur)

    # Conclusión
    print_header("✅ MIGRACIÓN COMPLETADA EXITOSAMENTE")

    print("\n📋 Próximos pasos:")
    print("   1. Verifica manualmente los datos migrados")
    print("   2. Prueba la aplicación")
    print("   3. Si todo funciona, elimina las tablas *_old:")
    print("      docker exec postgres psql -U user vigias -c \"DROP TABLE cameras_old, events_old, faces_old, camera_stats_old;\"")
    print("\n   4. Actualiza inference/database.py para usar UUIDs")
    print("   5. Actualiza router/app/models.py (ya debería coincidir)")

    print("\n💾 Backup disponible en:")
    print("   database/backup_before_uuid_migration_*.sql")

    cur.close()
    conn.close()

if __name__ == "__main__":
    main()
