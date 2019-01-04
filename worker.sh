#!/usr/bin/env bash

cd /var/www/moa

export MOA_CONFIG=ProductionConfig
pipenv run python -m moa.worker >> logs/worker.log 2>&1
