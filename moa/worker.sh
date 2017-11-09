#!/usr/bin/env bash

cd /var/www/moa
source ../.moa-venv/bin/activate

export MOA_CONFIG=ProductionConfig
python moa/worker.py >> logs/worker.log 2>&1
