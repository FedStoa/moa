import importlib
import logging
import os
import sys
from datetime import datetime

import twitter
from mastodon import Mastodon, MastodonAPIError, MastodonNetworkError
from sqlalchemy import create_engine, exc
from sqlalchemy.orm import Session
from twitter import TwitterError

from moa.helpers import FORMAT
from moa.models import Bridge, Mapping, WorkerStat, BridgeMetadata

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

l = logging.getLogger('balance')

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

bridges = session.query(Bridge).filter_by(enabled=True)

for bridge in bridges:
    print(bridge)

    if not bridge.md:
        bridge.md = BridgeMetadata()

        mastodonhost = bridge.mastodon_host

        mast_api = Mastodon(
                client_id=mastodonhost.client_id,
                client_secret=mastodonhost.client_secret,
                api_base_url=f"https://{mastodonhost.hostname}",
                access_token=bridge.mastodon_access_code,
                debug_requests=False,
                request_timeout=15,
                ratelimit_method='throw'
        )

        try:
            profile = mast_api.account_verify_credentials()
            bridge.md.is_bot = profile['bot']

            statuses = mast_api.account_statuses(bridge.mastodon_account_id)
            if len(statuses) > 0:
                bridge.md.last_toot = statuses[0]["created_at"]

        except (MastodonAPIError, MastodonNetworkError) as e:
            l.error(e)
            session.commit()
            continue

        twitter_api = twitter.Api(
                consumer_key=c.TWITTER_CONSUMER_KEY,
                consumer_secret=c.TWITTER_CONSUMER_SECRET,
                access_token_key=bridge.twitter_oauth_token,
                access_token_secret=bridge.twitter_oauth_secret,
                tweet_mode='extended'  # Allow tweets longer than 140 raw characters
        )
        try:
            tl = twitter_api.GetUserTimeline()
        except TwitterError as e:
            l.error(e)
        else:
            if len(tl) > 0:
                d = datetime.strptime(tl[0].created_at, '%a %b %d %H:%M:%S %z %Y')
                bridge.md.last_tweet = d

        session.commit()

session.close()
db_connection.close()


