#!/usr/bin/env bash

export MOA_CONFIG=config.ProductionConfig
export FLASK_APP=app.py

flask db $@
