#!/bin/bash
cd ~/.openclaw/workspace/plottr-detection
export PYTHONPATH=.
# Load environment variables from .env
set -a
source .env
set +a
python3 -u etl/download_bulk.py 2>&1 | tee /tmp/download.log