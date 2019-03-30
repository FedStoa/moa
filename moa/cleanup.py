import importlib
import logging
import os
import sys
from datetime import datetime, timedelta

from sqlalchemy import create_engine, exc
from sqlalchemy.orm import Session

from moa.models import Bridge, Mapping, WorkerStat

moa_config = os.environ.get('MOA_CONFIG', 'DevelopmentConfig')
c = getattr(importlib.import_module('config'), moa_config)

if c.SENTRY_DSN:
    from raven import Client

    client = Client(c.SENTRY_DSN)

FORMAT = "%(asctime)-15s [%(process)d] [%(filename)s:%(lineno)s : %(funcName)s()] %(message)s"

logging.basicConfig(format=FORMAT)

l = logging.getLogger('cleanup')

if c.DEBUG:
    l.setLevel(logging.DEBUG)
else:
    l.setLevel(logging.INFO)

l.info("Starting up…")
engine = create_engine(c.SQLALCHEMY_DATABASE_URI)
engine.connect()

try:
    engine.execute('SELECT 1 from bridge')
except exc.SQLAlchemyError as e:
    l.error(e)
    sys.exit()

session = Session(engine)

# Remove disabled bridges older than 30 days
target_date = datetime.now() - timedelta(days=30)
session.query(Bridge).filter_by(enabled=False).filter(Bridge.updated < target_date).delete()

# Remove mappings older than 4 months
target_date = datetime.now() - timedelta(days=120)
session.query(Mapping).filter(Mapping.created < target_date).delete()

# Remove worker stats older than 4 months
target_date = datetime.now() - timedelta(days=120)
session.query(WorkerStat).filter(WorkerStat.created < target_date).delete()

session.commit()
