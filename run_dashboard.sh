#!/bin/bash
cd "$(dirname "$0")"
source .venv/bin/activate
echo "Starting GadgetFlow Dashboard on http://0.0.0.0:8080 ..."
exec uvicorn app:app --host 0.0.0.0 --port 8080 --reload
