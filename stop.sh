#!/bin/zsh
PID_FILE=~/.n8n-mcp-server/tmp/mcp.pid
[ -f "$PID_FILE" ] && kill "$(cat $PID_FILE)" && rm "$PID_FILE"
echo "n8n-mcp-server stopped"

