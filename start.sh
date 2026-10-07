#!/usr/bin/env bash
# Render start command: runs the ingestion worker in the background and the dashboard in front.
set -e
mkdir -p data logs
python worker.py --init
# Restart the worker if it ever exits/crashes, so data keeps updating.
(while true; do python worker.py; echo "worker exited ($?); restarting in 30s"; sleep 30; done) &
exec streamlit run app.py --server.address 0.0.0.0 --server.port "${PORT:-8501}" --server.headless true
