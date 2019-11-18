import importlib
import logging
import os
import sys
from datetime import datetime, timedelta

from sqlalchemy import create_engine, exc
from sqlalchemy.orm import Session

from moa.models import CON_XP_UNLESS, TSettings

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

print("Starting up…")
engine = create_engine(c.SQLALCHEMY_DATABASE_URI)
db_connection = engine.connect()

try:
    engine.execute('SELECT 1 from bridge')
except exc.SQLAlchemyError as e:
    print(e)
    sys.exit()

session = Session(engine)

# Remove disabled bridges older than 30 days
target_date = datetime.now() - timedelta(days=30)

settings = session.query(TSettings).filter_by(conditional_posting_old=1)
for s in settings:
    s.conditional_posting = CON_XP_UNLESS
    session.commit()

session.close()
db_connection.close()
