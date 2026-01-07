# VIGIAS-IA - GUÍA DE INSTALACIÓN Y DESPLIEGUE

**Versión**: 2.0.0-beta (Sprint 1 Day 1)
**Fecha**: 2025-12-26
**Sistema**: Ubuntu 20.04+ con GPU NVIDIA

Ver contenido completo en CAMBIOS_SPRINT1_DAY1.md (Sección: Instalación)

---

## 🚀 INICIO RÁPIDO

### Levantar todos los servicios

```bash
cd /home/logisticos-two/dev

# 1. Servicios de bases de datos
docker-compose up -d postgres vision-postgres keycloak-db maps-postgres

# 2. Infraestructura (esperar 30s)
sleep 30
docker-compose up -d config-server eureka-server keycloak vision-nats vision-redis

# 3. Microservicios (esperar 30s)
sleep 30
docker-compose up -d api-gateway config-ms identity-ms organization-ms ops-ms

# 4. Vision AI services
docker-compose up -d vision-router maps-api vision-ingest

# 5. Inference service (Python miniconda)
cd Proyect_Computer_Vision
conda activate vigias
nohup python -u -m inference.main > /tmp/inference.log 2>&1 &
```

### Verificar que todo funciona

```bash
# Health checks
curl http://localhost:8003/health          # Router API
curl http://localhost:8080/actuator/health # API Gateway  
curl http://localhost:8761/                # Eureka

# Ver logs
docker-compose logs -f vision-router
tail -f /tmp/inference.log

# Ver stream de debug
firefox http://localhost:5000/debug/cam_01/mjpeg
```

---

## 📋 REQUISITOS

- Ubuntu 22.04 LTS
- Docker + Docker Compose
- NVIDIA Driver 535+
- Python 3.11 (Miniconda)
- 16GB RAM mínimo (32GB recomendado)
- GPU NVIDIA (GTX 1660+ con 6GB VRAM)

---

## 🔧 SOLUCIÓN DE PROBLEMAS COMUNES

### Puerto 8003 no responde

```bash
docker-compose restart vision-router
docker logs -f dev-vision-router-1
```

### Inference no conecta a DB

```bash
# Verificar puertos expuestos
docker ps | grep vision-postgres  # Debe mostrar 0.0.0.0:5436->5432/tcp

# Si no, recrear contenedor
docker-compose stop vision-postgres
docker-compose rm -f vision-postgres  
docker-compose up -d vision-postgres
```

### GPU no detectada

```bash
nvidia-smi  # Ver estado de GPU
python -c "import torch; print(torch.cuda.is_available())"  # Debe ser True
```

---

Para documentación completa, ver archivos:
- **CAMBIOS_SPRINT1_DAY1.md** - Detalle de todos los cambios
- **AgentFiles/PLAN_DESARROLLO_PRODUCCION.md** - Roadmap completo
