#!/usr/bin/env bash
# Real-time log viewer for EduNews24
# Usage: bash scripts/watch-logs.sh

DATE=$(date +%Y-%m-%d)
LOGS_DIR="$(cd "$(dirname "$0")/.." && pwd)/logs"

BACKEND_LOG="$LOGS_DIR/backend-$DATE.log"
FRONTEND_LOG="$LOGS_DIR/frontend-$DATE.log"

echo "=================================="
echo " EduNews24 — Log Viewer"
echo " Date: $DATE"
echo "=================================="
echo ""
echo " Backend:  $BACKEND_LOG"
echo " Frontend: $FRONTEND_LOG"
echo ""
echo " Press Ctrl+C to stop"
echo "=================================="
echo ""

# Create files if they don't exist so tail -f doesn't error
touch "$BACKEND_LOG" "$FRONTEND_LOG"

tail -f "$BACKEND_LOG" "$FRONTEND_LOG"
