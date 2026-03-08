#!/bin/bash
echo ""
echo "  ╔══════════════════════════════════╗"
echo "  ║     ARENA — AI Debate System     ║"
echo "  ╚══════════════════════════════════╝"
echo ""

# Check Ollama is running
if ! curl -s http://localhost:11434/api/tags > /dev/null 2>&1; then
    echo "  ⚠️  Ollama is not running. Starting it..."
    ollama serve &
    sleep 3
fi

echo "  ✓ Ollama is running"
echo ""

# Check models
echo "  Checking models..."
MODELS=$(curl -s http://localhost:11434/api/tags | python3 -c "import sys,json; d=json.load(sys.stdin); [print('  ✓', m['name']) for m in d.get('models',[])]" 2>/dev/null)
echo "$MODELS"
echo ""

# Install deps if needed
pip install fastapi uvicorn httpx websockets pydantic --break-system-packages -q 2>/dev/null

echo "  🚀 Starting Arena on http://localhost:8765"
echo ""

cd "$(dirname "$0")"
python3 server.py
