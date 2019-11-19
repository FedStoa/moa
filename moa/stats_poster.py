import importlib
import logging
import os
import sys
from datetime import datetime, timedelta

import pandas as pd
import pygal
from mastodon import Mastodon
from sqlalchemy import create_engine, exc
from sqlalchemy.orm import Session

from moa.helpers import FORMAT
from moa.models import Bridge, WorkerStat

"""
You need an app access code for this run. Create one at Preferences->Development->New Application
It only needs the 'write:media' and 'write:statuses' scopes 

"""

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

l = logging.getLogger('stats')

if c.DEBUG:
    l.setLevel(logging.DEBUG)
else:
    l.setLevel(logging.INFO)

l.debug("Starting up…")
engine = create_engine(c.SQLALCHEMY_DATABASE_URI)
db_connection = engine.connect()

try:
    engine.execute('SELECT 1 from bridge')
except exc.SQLAlchemyError as e:
    l.error(e)
    sys.exit()

session = Session(engine)

# Get user count
user_count = session.query(Bridge).filter_by(enabled=1).count()
msg = f"Active Users: {user_count}"

# Create count graph
since = datetime.now() - timedelta(hours=24 * 7)

stats_query = session.query(WorkerStat).filter(WorkerStat.created > since).with_entities(WorkerStat.created, WorkerStat.toots, WorkerStat.tweets, WorkerStat.instas)

df = pd.read_sql(stats_query.statement, stats_query.session.bind)
df.set_index(['created'], inplace=True)

df.groupby(level=0).sum()
r = df.resample('h').sum()
r = r.fillna(0)

toots = r['toots'].tolist()
tweets = r['tweets'].tolist()
instas = r['instas'].tolist()

chart = pygal.StackedBar(title="# of Messages (1 week)",
                         human_readable=True,
                         legend_at_bottom=True)
chart.add('Toots', toots)
chart.add('Tweets', tweets)
chart.add('Instas', instas)
upload_file_name = '/tmp/chart.png'
attachment_desc = 'graph of messages in Moa'

chart.render_to_png(upload_file_name)

# Post it
mast_api = Mastodon(
        api_base_url=c.STATS_POSTER_BASE_URL,
        access_token=c.STATS_POSTER_ACCESS_TOKEN,
        debug_requests=False,
        request_timeout=15,
        ratelimit_method='throw'
)

l.debug(f'Uploading {attachment_desc}: {upload_file_name}')
media_ids = []

try:
    media_ids.append(mast_api.media_post(upload_file_name, description=attachment_desc))

finally:
    os.unlink(upload_file_name)

post = mast_api.status_post(
        msg,
        media_ids=media_ids,
        visibility='public',
        sensitive=False,
        )
