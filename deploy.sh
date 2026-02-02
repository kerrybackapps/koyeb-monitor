#!/bin/bash
# deploy.sh - Deploy koyeb-monitor to Koyeb
#
# Usage:
#   ./deploy.sh [region]
#
# Arguments:
#   region: Koyeb region (default: sin for Singapore/Asia)
#           Options: sin (Singapore), was (Washington), fra (Frankfurt)
#
# Required environment variables:
#   KOYEB_API_TOKEN: Your Koyeb API token
#
# The monitor URL will be: https://koyeb-monitor-<your-koyeb-org>.koyeb.app

set -e

# Parse arguments
REGION=${1:-sin}

# Validate region
if [[ ! "$REGION" =~ ^(sin|was|fra)$ ]]; then
    echo "ERROR: Invalid region '$REGION'"
    echo "Valid regions: sin (Singapore), was (Washington), fra (Frankfurt)"
    exit 1
fi

# Load environment variables from .env file if it exists
if [ -f ".env" ]; then
    echo "Loading credentials from .env file..."
    while IFS='=' read -r key value; do
        [[ "$key" =~ ^#.*$ ]] && continue
        [[ -z "$key" ]] && continue
        key=$(echo "$key" | xargs)
        value=$(echo "$value" | xargs)
        value="${value%\"}"
        value="${value#\"}"
        if [ -z "${!key}" ]; then
            export "$key=$value"
        fi
    done < .env
fi

# Also try parent directory .env (for bop-run-upload/.env)
if [ -f "../bop-run-upload/.env" ]; then
    echo "Loading credentials from ../bop-run-upload/.env..."
    while IFS='=' read -r key value; do
        [[ "$key" =~ ^#.*$ ]] && continue
        [[ -z "$key" ]] && continue
        key=$(echo "$key" | xargs)
        value=$(echo "$value" | xargs)
        value="${value%\"}"
        value="${value#\"}"
        if [ -z "${!key}" ]; then
            export "$key=$value"
        fi
    done < ../bop-run-upload/.env
fi

# Check required environment variables
if [ -z "$KOYEB_API_TOKEN" ]; then
    echo "ERROR: KOYEB_API_TOKEN environment variable not set"
    exit 1
fi

APP_NAME="koyeb-monitor"
GIT_REPO="kerrybackapps/koyeb-monitor"
GIT_BRANCH=$(git branch --show-current 2>/dev/null || echo "main")

echo "=========================================="
echo "KOYEB MONITOR DEPLOYMENT"
echo "=========================================="
echo "Configuration:"
echo "  App name:    $APP_NAME"
echo "  Region:      $REGION"
echo "  Git repo:    $GIT_REPO"
echo "  Git branch:  $GIT_BRANCH"
echo "=========================================="
echo ""

# Check if koyeb CLI is installed
if ! command -v koyeb &> /dev/null; then
    echo "ERROR: koyeb CLI not found"
    exit 1
fi

# Check if app exists
echo "Checking if app '$APP_NAME' exists..."
if koyeb apps get "$APP_NAME" --token "$KOYEB_API_TOKEN" &> /dev/null; then
    echo "App exists. Deleting old app first..."
    echo "yes" | koyeb apps delete "$APP_NAME" --token "$KOYEB_API_TOKEN"
    echo "Waiting for deletion..."
    sleep 5
fi

# Create new app
echo "Creating app '$APP_NAME'..."
koyeb apps create "$APP_NAME" --token "$KOYEB_API_TOKEN"
echo "✓ App created"

# Create the web service
echo "Creating web service..."
koyeb services create web \
  --app "$APP_NAME" \
  --type web \
  --git "github.com/$GIT_REPO" \
  --git-branch "$GIT_BRANCH" \
  --git-buildpack-run-command "gunicorn app:app" \
  --instance-type nano \
  --regions "$REGION" \
  --port 8000:http \
  --route /:8000 \
  --env KOYEB_API_TOKEN="$KOYEB_API_TOKEN" \
  --token "$KOYEB_API_TOKEN"

echo ""
echo "=========================================="
echo "DEPLOYMENT STARTED"
echo "=========================================="
echo ""
echo "Monitor URL will be:"
echo "  https://koyeb-monitor-<your-org>.koyeb.app"
echo ""
echo "Check deployment status:"
echo "  koyeb services get web --app $APP_NAME --token \$KOYEB_API_TOKEN"
echo ""
echo "View logs:"
echo "  koyeb services logs web --app $APP_NAME --tail --token \$KOYEB_API_TOKEN"
echo ""
echo "IMPORTANT: After deployment, update MONITOR_URL in bop-run-upload/.env"
echo "=========================================="
