import importlib
import logging
import os
import sys
from datetime import datetime, timedelta
from moa.helpers import FORMAT
from sqlalchemy import create_engine, exc
from sqlalchemy.orm import Session

from moa.models import Bridge, Mapping, WorkerStat, MastodonHost, TSettings, BridgeStat

moa_config = os.environ.get('MOA_CONFIG', 'DevelopmentConfig')
c = getattr(importlib.import_module('config'), moa_config)

if c.SENTRY_DSN:
    import sentry_sdk
    from sentry_sdk.integrations.logging import LoggingIntegration

    sentry_logging = LoggingIntegration(
            level=logging.INFO,  # Capture info and above as breadcrumbs
            event_level=logging.FATAL  # Only send fatal errors as events
    )
    sentry_sdk.init(dsn=c.SENTRY_DSN, integrations=[sentry_logging])

logging.basicConfig(format=FORMAT)

l = logging.getLogger('cleanup')

if c.DEBUG:
    l.setLevel(logging.DEBUG)
else:
    l.setLevel(logging.INFO)

l.info("Starting up…")
engine = create_engine(c.SQLALCHEMY_DATABASE_URI)
db_connection = engine.connect()

try:
    engine.execute('SELECT 1 from bridge')
except exc.SQLAlchemyError as e:
    l.error(e)
    sys.exit()

session = Session(engine)

# Remove disabled bridges older than 30 days
target_date = datetime.now() - timedelta(days=30)

bridges = session.query(Bridge).filter_by(enabled=False).filter_by(updated=None)
for b in bridges:
    settings = b.t_settings
    md = b.md
    session.delete(b)
    session.delete(settings)
    if md:
        session.delete(md)
    session.commit()

bridges = session.query(Bridge).filter_by(enabled=False).filter(Bridge.updated < target_date)
for b in bridges:
    bridge_stats = session.query(BridgeStat).filter(BridgeStat.bridge_id == b.id).delete()
    session.commit()

    settings = b.t_settings
    md = b.md
    session.delete(b)
    session.delete(settings)
    if md:
        session.delete(md)
    session.commit()


orphaned_settings = session.query(TSettings).filter(~TSettings.bridge.any()).all()
for s in orphaned_settings:
    session.delete(s)
    session.commit()

# Remove mappings older than 4 months
target_date = datetime.now() - timedelta(days=120)
session.query(Mapping).filter(Mapping.created < target_date).delete()
session.commit()

# Remove worker stats older than 4 months
target_date = datetime.now() - timedelta(days=120)
session.query(WorkerStat).filter(WorkerStat.created < target_date).delete()
session.commit()

# Remove hosts with no bridges
mhs = session.query(MastodonHost).filter(~MastodonHost.bridges.any()).all()

for m in mhs:
    session.delete(m)

session.commit()

session.close()
db_connection.close()
