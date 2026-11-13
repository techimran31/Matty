#!/bin/bash
# ==============================================================================
#  MATTY AI PERSONAL ASSISTANT - 1-CLICK MACOS / LINUX SETUP SCRIPT
# ==============================================================================

set -e

echo ""
echo "=================================================================="
echo "          ⚡ WELCOME TO MATTY AI ASSISTANT SETUP ⚡             "
echo "=================================================================="
echo ""

# STEP 1 - check that Python 3 is installed
if ! command -v python3 &> /dev/null; then
    echo "❌ Python 3 is not installed. Please install Python 3.10+ and re-run."
    exit 1
fi

echo "✅ Python $(python3 --version) detected."

# STEP 2 - create and activate an isolated environment
if [ ! -d ".venv" ]; then
    echo "📦 Creating isolated Python environment (.venv)..."
    python3 -m venv .venv
fi

echo "📦 Activating environment..."
source .venv/bin/activate

# STEP 3 - upgrade pip, then install requirements.txt
#          (speech recognition, speech output, GUI, market data, WhatsApp)
#          Always use "python3 -m pip": some systems block the pip binary.
echo "⬇️  Installing required packages..."
python3 -m pip install --upgrade pip
python3 -m pip install -r requirements.txt

# STEP 4 - store the free Groq API key in .env as GROQ_API_KEY
#          Pressing Enter instead keeps Matty in offline mode, which still
#          supports every local action (apps, volume, power, WhatsApp, mail).
ENV_FILE="$(cd "$(dirname "$0")" && pwd)/.env"

if ! grep -q '^GROQ_API_KEY=' "$ENV_FILE" 2>/dev/null; then
    echo ""
    echo "🔑 Setup your free Groq API key (from https://console.groq.com/keys):"
    read -p "Enter Groq API Key (or press Enter to skip and use local offline mode): " API_KEY
    if [ -n "$API_KEY" ]; then
        echo "GROQ_API_KEY=$API_KEY" >> "$ENV_FILE"
        chmod 600 "$ENV_FILE"
        echo "✅ API Key saved to .env."
    else
        echo "⚠️ Skipping API key. Matty will run in local offline mode."
    fi
else
    echo "✅ Found existing Groq API key in .env."
fi

# STEP 5 - print how to launch, then optionally start Matty now
echo ""
echo "=================================================================="
echo "          🎉 MATTY SETUP COMPLETED SUCCESSFULLY!                "
echo "=================================================================="
echo ""
echo "To start Matty at any time, run:"
echo "    source .venv/bin/activate && python matty_voice.py"
echo ""
echo "To open the 3D Holographic Workplace HUD, open:"
echo "    matty_workplace.html in your browser"
echo ""

read -p "Would you like to start Matty now? (y/n): " START_NOW
if [[ "$START_NOW" =~ ^[Yy]$ ]]; then
    python matty_voice.py
fi
