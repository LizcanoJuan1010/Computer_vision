# VIGIAS-IA Monitoring Stack

Complete observability stack for VIGIAS-IA computer vision platform using Prometheus, Grafana, and Alertmanager.

## 📊 Stack Components

| Component | Port | Purpose |
|-----------|------|---------|
| **Prometheus** | 9090 | Metrics collection and storage |
| **Alertmanager** | 9093 | Alert routing and notification management |
| **Grafana** | 3000 | Dashboards and visualization |
| **Node Exporter** | 9100 | System-level metrics (CPU, memory, disk) |
| **Postgres Exporter** | 9187 | Database metrics |
| **Redis Exporter** | 9121 | Cache metrics |

---

## 🚀 Quick Start

### 1. Start Monitoring Stack

```bash
cd monitoring
docker-compose -f docker-compose.monitoring.yml up -d
```

### 2. Access Dashboards

- **Grafana**: http://localhost:3000
  - User: `admin`
  - Password: `admin` (change on first login)

- **Prometheus**: http://localhost:9090
- **Alertmanager**: http://localhost:9093

### 3. Import Dashboards

Grafana dashboards are automatically provisioned from `grafana/dashboards/`:
- **System Overview** - vigias-system-overview.json
- **Camera Health** - vigias-cameras.json

---

## 📈 Available Metrics

### API Metrics
- `vigias_api_requests_total` - Total API requests by method, endpoint, status
- `vigias_api_request_duration_seconds` - API latency histogram

### Event Metrics
- `vigias_events_created_total` - Events created by type and severity
- `vigias_events_by_status` - Current events by status
- `vigias_event_processing_duration_seconds` - Event processing time

### Notification Metrics
- `vigias_notifications_sent_total` - Notifications sent by channel and status
- `vigias_notification_delivery_duration_seconds` - Notification delivery time
- `vigias_notification_rules_evaluated_total` - Rules evaluated

### Camera Metrics
- `vigias_cameras_by_status` - Camera count by status (ONLINE/OFFLINE/ERROR)
- `vigias_camera_fps` - Current FPS per camera
- `vigias_camera_cpu_percent` - CPU usage per camera
- `vigias_camera_memory_mb` - Memory usage per camera
- `vigias_camera_frames_dropped_total` - Dropped frames counter

### System Metrics
- `vigias_nats_connected` - NATS connection status (1=connected)
- `vigias_redis_connected` - Redis connection status (1=connected)
- `vigias_db_connections_active` - Active database connections

---

## 🚨 Alert Rules

### Camera Alerts
- **CameraOffline**: Camera offline for >5min (HIGH)
- **CameraError**: Camera in ERROR state >2min (CRITICAL)
- **LowCameraFPS**: FPS <5 for >3min (WARNING)
- **HighCameraCPU**: CPU >90% for >5min (WARNING)
- **HighCameraMemory**: Memory >500MB for >5min (WARNING)

### Event Alerts
- **HighCriticalEventRate**: >0.5 CRITICAL events/sec (CRITICAL)
- **SecurityEventSpike**: >0.1 intrusion events/sec (HIGH)

### Notification Alerts
- **HighNotificationFailureRate**: >20% failures for >5min (WARNING)
- **SlowNotificationDelivery**: p95 >10s for >5min (WARNING)

### API Alerts
- **HighAPIErrorRate**: >5% 5xx errors for >5min (HIGH)
- **SlowAPIResponses**: p95 >1s for >5min (WARNING)

### Infrastructure Alerts
- **NATSDisconnected**: NATS down for >1min (CRITICAL)
- **RedisDisconnected**: Redis down for >1min (CRITICAL)
- **DatabaseConnectionPoolExhausted**: >90 connections (HIGH)

---

## 🔔 Alert Routing

Alerts are routed based on severity:

### Critical Alerts → `critical-alerts` receiver
- Email to oncall@company.com + ops-team@company.com
- Slack notification to #vigias-critical-alerts
- Webhook to VIGIAS API

### High Alerts → `high-alerts` receiver
- Email to ops-team@company.com
- Slack notification to #vigias-alerts

### Warning Alerts → `warning-alerts` receiver
- Email to ops-team@company.com

---

## ⚙️ Configuration

### Prometheus

Edit `prometheus/prometheus.yml` to:
- Change scrape intervals
- Add new scrape targets
- Configure remote write

### Alertmanager

Edit `alertmanager/alertmanager.yml` to:
- Configure SMTP settings for emails
- Add Slack webhooks
- Adjust alert routing
- Set inhibition rules

### Grafana

Import additional dashboards or create custom ones at http://localhost:3000

---

## 📝 Example PromQL Queries

### API Performance
```promql
# Request rate per endpoint
sum(rate(vigias_api_requests_total[5m])) by (endpoint)

# p95 latency
histogram_quantile(0.95, sum(rate(vigias_api_request_duration_seconds_bucket[5m])) by (le, endpoint))

# Error rate
rate(vigias_api_requests_total{status_code=~"5.."}[5m]) / rate(vigias_api_requests_total[5m])
```

### Camera Health
```promql
# Cameras online
vigias_cameras_by_status{status="ONLINE"}

# Average FPS across all cameras
avg(vigias_camera_fps)

# Total frames dropped last hour
sum(increase(vigias_camera_frames_dropped_total[1h]))
```

### Event Analysis
```promql
# Event creation rate by type
sum(rate(vigias_events_created_total[5m])) by (event_type)

# Critical events in last 24h
sum(increase(vigias_events_created_total{severity="CRITICAL"}[24h]))
```

### Notification Performance
```promql
# Notification success rate
sum(rate(vigias_notifications_sent_total{status="SENT"}[5m])) /
sum(rate(vigias_notifications_sent_total[5m]))

# Average delivery time by channel
avg(vigias_notification_delivery_duration_seconds) by (channel_type)
```

---

## 🔧 Troubleshooting

### Metrics not appearing in Prometheus

1. Check Router is exposing metrics:
```bash
curl http://localhost:8003/metrics
```

2. Check Prometheus targets:
http://localhost:9090/targets

3. Verify network connectivity:
```bash
docker exec vigias-prometheus ping router
```

### Alerts not firing

1. Check alert rules are loaded:
http://localhost:9090/alerts

2. Verify Alertmanager is receiving alerts:
http://localhost:9093/#/alerts

3. Test alert evaluation:
```bash
docker exec vigias-prometheus promtool check rules /etc/prometheus/alerts/vigias-alerts.yml
```

### Grafana dashboards empty

1. Check Prometheus datasource is configured
2. Verify metrics exist in Prometheus
3. Check dashboard time range

---

## 🔒 Security Notes

**Before Production:**
1. Change Grafana admin password
2. Update Alertmanager SMTP credentials
3. Configure firewall rules (restrict ports 9090, 9093 to internal network)
4. Enable authentication on Prometheus/Alertmanager
5. Use TLS for all communications
6. Replace default Slack webhook URLs

---

## 📚 Additional Resources

- [Prometheus Documentation](https://prometheus.io/docs/)
- [Grafana Dashboards](https://grafana.com/grafana/dashboards/)
- [Alertmanager Guide](https://prometheus.io/docs/alerting/latest/alertmanager/)
- [PromQL Basics](https://prometheus.io/docs/prometheus/latest/querying/basics/)

---

## 🆘 Support

For issues or questions:
1. Check logs: `docker-compose -f docker-compose.monitoring.yml logs -f`
2. Review Prometheus configuration: http://localhost:9090/config
3. Test PromQL queries: http://localhost:9090/graph
