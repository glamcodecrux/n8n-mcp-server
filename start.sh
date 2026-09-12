#!/bin/zsh
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
cd ~/.n8n-mcp-server
source venv/bin/activate
nohup python server.py >> logs/mcp.log 2>&1 &
echo $! > tmp/mcp.pid
echo "n8n-mcp-server started PID=$(cat tmp/mcp.pid)"

