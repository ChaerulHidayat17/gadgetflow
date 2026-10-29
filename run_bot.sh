#!/bin/bash
cd "$(dirname "$0")"
source .venv/bin/activate
echo "Starting GadgetFlow Telegram Bot Worker..."
exec python3 bot.py "$@"
