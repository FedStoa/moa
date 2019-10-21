import argparse
import importlib
import logging
import os
import smtplib
import sys
import time
from datetime import datetime
from http.client import IncompleteRead
from pathlib import Path
from typing import Any, List

import psutil
import requests
import twitter
from httplib2 import ServerNotFoundError
from instagram import InstagramAPI, InstagramAPIError, InstagramClientError
from instagram.helper import datetime_to_timestamp
from mastodon import Mastodon
from mastodon.Mastodon import MastodonAPIError, MastodonNetworkError, MastodonRatelimitError, MastodonServerError
from requests import ConnectionError
from sqlalchemy import create_engine, exc, func
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import ObjectDeletedError
from twitter import TwitterError

from moa.helpers import email_deferral, MoaMediaUploadException
from moa.insta import Insta
from moa.models import Bridge, WorkerStat, DEFER_OK, DEFER_FAILED, BridgeStat
from moa.toot import Toot
from moa.toot_poster import TootPoster
from moa.tweet import Tweet
from moa.tweet_poster import TweetPoster

start_time = time.time()

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

parser = argparse.ArgumentParser(description='Moa Worker')
parser.add_argument('--worker', dest='worker', type=int, required=False, default=1)
args = parser.parse_args()

worker_stat = WorkerStat(worker=args.worker)
worker_stat.time = 0

FORMAT = "%(asctime)-15s [%(process)d] [%(filename)s:%(lineno)s : %(funcName)s()] %(message)s"

logging.basicConfig(format=FORMAT)

l = logging.getLogger('worker')

if c.DEBUG:
    l.setLevel(logging.DEBUG)
else:
    l.setLevel(logging.INFO)

# logging.getLogger('sqlalchemy.engine').setLevel(logging.INFO)

l.info("Starting up…")
engine = create_engine(c.SQLALCHEMY_DATABASE_URI)
try:
    engine.connect()
except OperationalError as e:
    print(e, file=sys.stderr)
    l.error(e)
    sys.exit(1)

try:
    engine.execute('SELECT 1 from bridge')
except exc.SQLAlchemyError as e:
    l.error(e)
    sys.exit()

session = Session(engine)

lockfile = Path(f'worker_{args.worker}.lock')


def check_worker_stop():
    if Path('worker_stop').exists():
        l.info("Worker paused...exiting")
        session.add(worker_stat)
        session.commit()
        session.close()
        try:
            lockfile.unlink()
        except FileNotFoundError:
            pass

        exit(0)


check_worker_stop()

if Path(lockfile).exists():
    l.info("Worker lock found")
    with lockfile.open() as f:
        pid = f.readline()
        try:
            pid = int(pid)
        except ValueError:
            l.info("Corrupt lock file found")
            lockfile.unlink()

        else:
            if pid in psutil.pids():
                l.info("Worker process still running...exiting")
                session.commit()
                session.close()
                exit(0)
            else:
                l.info("Stale Worker found")

with lockfile.open('wt') as f:
    f.write(str(psutil.Process().pid))

if not c.SEND:
    l.warning("SENDING IS NOT ENABLED")

bridges = session.query(Bridge).filter_by(enabled=True).filter_by(worker_id=args.worker)

if 'sqlite' not in c.SQLALCHEMY_DATABASE_URI and not c.DEVELOPMENT:
    bridges = bridges.order_by(func.rand())

bridge_count = 0

for bridge in bridges:
    # l.debug(bridge.t_settings.__dict__)
    total_time = time.time() - start_time

    if total_time > 60 * 4.5:
        continue

    try:
        _ = bridge.id
    except ObjectDeletedError:
        # in case the row is removed during a run
        continue

    #
    # Fetch from Mastodon
    #
    new_toots: List[Any] = []

    if not bridge.mastodon_access_code:
        bridge.enabled = False
        session.commit()
    else:
        mastodon_last_id = bridge.mastodon_last_id
        mastodonhost = bridge.mastodon_host

        if mastodonhost.defer_until and mastodonhost.defer_until > datetime.now():
            l.warning(f"Deferring connections to {mastodonhost.hostname}")
            continue

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
            new_toots = mast_api.account_statuses(
                    bridge.mastodon_account_id,
                    since_id=bridge.mastodon_last_id
            )
        except MastodonAPIError as e:
            msg = f"{bridge.mastodon_user}@{mastodonhost.hostname} MastodonAPIError: {e}"
            l.error(msg)

            if any(x in repr(e) for x in ['revoked', 'invalid', 'not found', 'Forbidden', 'Unauthorized', 'Bad Request',
                                          'Name or service not known',]):
                l.warning(f"Disabling bridge for user {bridge.mastodon_user}@{mastodonhost.hostname}")
                bridge.mastodon_access_code = None
                bridge.enabled = False
            else:
                r = mastodonhost.defer()

                if r == DEFER_OK and c.SEND_DEFERRED_EMAIL:
                    email_deferral(c, mastodonhost, l, msg)

                elif r == DEFER_FAILED and c.SEND_DEFER_FAILED_EMAIL:
                    msg2 = f"Server Defer failed Disabling bridge for user {bridge.mastodon_user}@{mastodonhost.hostname}"
                    email_deferral(c, mastodonhost, l, f"{msg}\n{msg2}")
                    l.warning(msg2)
                    bridge.mastodon_access_code = None
                    bridge.enabled = False

            session.commit()

            continue

        except MastodonServerError as e:
            msg = f"{bridge.mastodon_user}@{mastodonhost.hostname} MastodonServerError: {e}"
            l.error(msg)

            if any(x in repr(e) for x in ['revoked', 'invalid', 'not found', 'Forbidden', 'Unauthorized', 'Bad Request',
                                          'Name or service not known']):
                l.warning(f"Disabling bridge for user {bridge.mastodon_user}@{mastodonhost.hostname}")
                bridge.mastodon_access_code = None
                bridge.enabled = False
            else:
                r = mastodonhost.defer()

                if r == DEFER_OK and c.SEND_DEFERRED_EMAIL:
                    email_deferral(c, mastodonhost, l, msg)

                elif r == DEFER_FAILED and c.SEND_DEFER_FAILED_EMAIL:
                    msg2 = f"Server Defer failed Disabling bridge for user {bridge.mastodon_user}@{mastodonhost.hostname}"
                    email_deferral(c, mastodonhost, l, f"{msg}\n{msg2}")
                    l.warning(msg2)
                    bridge.mastodon_access_code = None
                    bridge.enabled = False

            session.commit()

            continue

        except MastodonNetworkError as e:
            msg = f"{bridge.mastodon_user}@{mastodonhost.hostname} MastodonNetworkError: {e}"
            l.error(msg)

            if any(x in repr(e) for x in ['revoked', 'invalid', 'not found', 'Forbidden', 'Unauthorized', 'Bad Request',
                                          'Name or service not known']):
                l.warning(f"Disabling bridge for user {bridge.mastodon_user}@{mastodonhost.hostname}")
                bridge.mastodon_access_code = None
                bridge.enabled = False
            else:
                r = mastodonhost.defer()

                if r == DEFER_OK and c.SEND_DEFERRED_EMAIL:
                    email_deferral(c, mastodonhost, l, msg)

                elif r == DEFER_FAILED and c.SEND_DEFER_FAILED_EMAIL:
                    msg2 = f"Server Defer failed Disabling bridge for user {bridge.mastodon_user}@{mastodonhost.hostname}"
                    email_deferral(c, mastodonhost, l, f"{msg}\n{msg2}")
                    l.warning(msg2)
                    bridge.mastodon_access_code = None
                    bridge.enabled = False

            session.commit()

            continue

        except MastodonRatelimitError as e:
            l.error(f"{bridge.mastodon_user}@{mastodonhost.hostname}: {e}")

        if len(new_toots) > c.MAX_MESSAGES_PER_RUN:
            l.error(f"{bridge.mastodon_user}@{mastodonhost.hostname}: Limiting to {c.MAX_MESSAGES_PER_RUN} messages")
            new_toots = new_toots[-c.MAX_MESSAGES_PER_RUN:]

        if c.SEND and len(new_toots) != 0:
            try:
                bridge.mastodon_last_id = int(new_toots[0]['id'])
            except ValueError:
                continue

            bridge.updated = datetime.now()

        new_toots.reverse()
        mastodonhost.defer_reset()
    #
    # Fetch from Twitter
    #
    new_tweets: List[Any] = []

    if bridge.twitter_oauth_token:
        twitter_last_id = bridge.twitter_last_id

        twitter_api = twitter.Api(
                consumer_key=c.TWITTER_CONSUMER_KEY,
                consumer_secret=c.TWITTER_CONSUMER_SECRET,
                access_token_key=bridge.twitter_oauth_token,
                access_token_secret=bridge.twitter_oauth_secret,
                tweet_mode='extended'  # Allow tweets longer than 140 raw characters
        )

        try:
            new_tweets = twitter_api.GetUserTimeline(
                    since_id=bridge.twitter_last_id,
                    include_rts=True,
                    exclude_replies=False)

        except TwitterError as e:
            l.error(f"@{bridge.twitter_handle}: {e}")

            if 'Unknown' in e.message:
                continue
            # elif 'OAuthAccessTokenException' in e.message:
            #     l.warning(f"Disabling bridge for Twitter user {bridge.twitter_handle}")
            #     bridge.enabled = False

            elif isinstance(e.message, list) and len(e.message) > 0:
                if e.message[0]['code'] in [89, 326]:
                    l.warning(f"Disabling bridge for Twitter user {bridge.twitter_handle}")
                    bridge.twitter_oauth_token = None
                    bridge.twitter_oauth_secret = None
                    bridge.enabled = False

            continue

        except ConnectionError as e:
            continue

        if len(new_tweets) > c.MAX_MESSAGES_PER_RUN:
            l.error(f"@{bridge.twitter_handle}: Limiting to {c.MAX_MESSAGES_PER_RUN} messages")
            new_tweets = new_tweets[-c.MAX_MESSAGES_PER_RUN:]

        if c.SEND and len(new_tweets) != 0:
            bridge.twitter_last_id = new_tweets[0].id
            bridge.updated = datetime.now()

        new_tweets.reverse()

    #
    # Instagram
    #

    new_instas = []

    if bridge.instagram_access_code:

        api = InstagramAPI(access_token=bridge.instagram_access_code, client_secret=c.INSTAGRAM_SECRET)

        try:
            recent_media, _ = api.user_recent_media(user_id=bridge.instagram_account_id)
        except InstagramAPIError as e:
            l.error(f"{bridge.instagram_handle}: '{e.error_type}' {e.error_message}")

            if e.error_type == 'OAuthAccessTokenException':
                l.error(f"{bridge.instagram_handle}: Removing OAUTH token")
                bridge.instagram_access_code = None
                bridge.instagram_account_id = 0
                bridge.instagram_handle = None
                bridge.updated = datetime.now()
                session.commit()
        except InstagramClientError as e:
            l.error(f"{bridge.instagram_handle}: Client Error: {e.error_message}")

        except (ConnectionResetError, IncompleteRead, ServerNotFoundError) as e:
            l.error(f"{e}")
            continue

        else:
            for media in recent_media:

                ts = datetime_to_timestamp(media.created_time)

                if ts > bridge.instagram_last_id:
                    new_instas.append(media)

            if c.SEND and len(new_instas) != 0:
                bridge.instagram_last_id = datetime_to_timestamp(new_instas[0].created_time)

            new_instas.reverse()

    #
    # Post Toots to Twitter
    #

    bridge_stat = None

    if bridge.twitter_oauth_token:
        tweet_poster = TweetPoster(c.SEND, session, twitter_api, bridge)

        if bridge.mastodon_access_code:
            l.debug(f"{bridge.id}: M - {bridge.mastodon_user}@{mastodonhost.hostname}")

            tweet_poster = TweetPoster(c.SEND, session, twitter_api, bridge)

            if bridge.t_settings.post_to_twitter_enabled and len(new_toots) > 0:

                l.info(f"{len(new_toots)} new toots found")

                bridge_stat = BridgeStat(bridge.id)

                for toot in new_toots:

                    t = Toot(bridge.t_settings, toot, c)

                    try:
                        result = tweet_poster.post(t)
                    except MoaMediaUploadException as e:
                        continue

                    if result:
                        worker_stat.add_toot()
                        bridge_stat.add_toot()

    #
    # Post Tweets to Mastodon
    #

    if bridge.mastodon_access_code:
        toot_poster = TootPoster(c.SEND, session, mast_api, bridge)

        if bridge.twitter_oauth_token:
            l.debug(f"{bridge.id}: T - @{bridge.twitter_handle}")

            if bridge.t_settings.post_to_mastodon_enabled and len(new_tweets) > 0:
                l.info(f"{len(new_tweets)} new tweets found")

                if not bridge_stat:
                    bridge_stat = BridgeStat(bridge.id)

                for status in new_tweets:

                    tweet = Tweet(bridge.t_settings, status, twitter_api)

                    try:
                        result = toot_poster.post(tweet)

                    except MoaMediaUploadException as e:
                        continue

                    if result:
                        worker_stat.add_tweet()
                        bridge_stat.add_tweet()

    #
    # Post Instagram
    #

    if len(new_instas) > 0:
        l.debug(f"{bridge.id}: I - {bridge.instagram_handle}")

        if bridge.t_settings.instagram_post_to_mastodon or bridge.t_settings.instagram_post_to_twitter:
            l.info(f"{len(new_instas)} new instas found")

            if not bridge_stat:
                bridge_stat = BridgeStat(bridge.id)

            for data in new_instas:
                stat_recorded = False

                insta = Insta(bridge.t_settings, data)

                if not insta.should_skip_mastodon and bridge.mastodon_access_code:
                    toot_poster = TootPoster(c.SEND, session, mast_api, bridge)
                    result = toot_poster.post(insta)
                    if result:
                        worker_stat.add_insta()
                        stat_recorded = True

                if not insta.should_skip_twitter and bridge.twitter_oauth_token:
                    tweet_poster = TweetPoster(c.SEND, session, twitter_api, bridge)

                    result = tweet_poster.post(insta)
                    if result and not stat_recorded:
                        worker_stat.add_insta()
                        bridge_stat.add_insta()

    if bridge_stat and bridge_stat.items > 0:
        session.add(bridge_stat)

    if c.SEND:
        session.commit()

    end_time = time.time()
    worker_stat.time = end_time - start_time
    bridge_count = bridge_count + 1

    check_worker_stop()

if len(c.HEALTHCHECKS) >= args.worker:
    url = c.HEALTHCHECKS[args.worker - 1]
    try:
        requests.get(url)
    except Exception:
        pass

l.info(f"-- All done -> Total time: {worker_stat.formatted_time} / {worker_stat.items} items / {bridge_count} Bridges")

session.add(worker_stat)

session.commit()
session.close()

lockfile.unlink()
