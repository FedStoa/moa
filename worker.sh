#!/usr/bin/env bash

cd /var/www/moa
source .moa-venv/bin/activate

export MOA_CONFIG=ProductionConfig
python -m moa.worker >> logs/worker.log 2>&1
