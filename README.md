# Koyeb Monitor

A lightweight Flask service that monitors Koyeb worker apps and stores their logs.

## Deployment

Deploy to Koyeb using the deploy script:

```bash
# Deploy to Singapore (default, for Asia region)
./deploy.sh

# Deploy to specific region
./deploy.sh sin   # Singapore (Asia)
./deploy.sh was   # Washington (US East)
./deploy.sh fra   # Frankfurt (Europe)
```

## Configuration

After deployment, update the `MONITOR_URL` in `bop-run-upload/.env` with the new URL.

The monitor URL format is: `https://koyeb-monitor-<your-koyeb-org>.koyeb.app`

## Endpoints

- `GET /` - List all stored app logs
- `GET /logs/<app_name>` - View logs for a specific app
- `GET /logs-raw/<app_name>` - Get raw logs as plain text
- `GET /messages` - View all API messages (received/sent)
- `GET /health` - Health check
- `POST /register` - Register a new service
- `POST /kill` - Request app termination (currently disabled)
- `POST /init-logs` - Initialize log storage for an app
- `POST /submit-logs` - Submit logs from a running app

## Region Recommendations

Deploy the monitor to the same region as your worker apps for lower latency:
- **Asia (sin)**: For bgn/kp14/gs21 simulations running in Singapore
- **US (was)**: For simulations running in Washington

The current worker default is **sin** (Singapore).
