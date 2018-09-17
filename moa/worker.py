import argparse
import importlib
import logging
import os
import smtplib
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, List

import requests
import twitter
from instagram import InstagramAPI, InstagramAPIError, InstagramClientError
from instagram.helper import datetime_to_timestamp
from mastodon import Mastodon
from mastodon.Mastodon import MastodonAPIError, MastodonNetworkError
from requests import ConnectionError
from sqlalchemy import create_engine, exc, func
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import ObjectDeletedError
from twitter import TwitterError

from moa.insta import Insta
from moa.models import Bridge, WorkerStat
from moa.toot import Toot
from moa.toot_poster import TootPoster
from moa.tweet import Tweet
from moa.tweet_poster import TweetPoster

start_time = time.time()

moa_config = os.environ.get('MOA_CONFIG', 'DevelopmentConfig')
c = getattr(importlib.import_module('config'), moa_config)

if c.SENTRY_DSN:
    from raven import Client

    client = Client(c.SENTRY_DSN)

parser = argparse.ArgumentParser(description='Moa Worker')
parser.add_argument('--worker', dest='worker', type=int, required=False, default=1)
args = parser.parse_args()

worker_stat = WorkerStat(worker=args.worker)
worker_stat.time = 0

FORMAT = "%(asctime)-15s [%(filename)s:%(lineno)s : %(funcName)s()] %(message)s"

logging.basicConfig(format=FORMAT)

l = logging.getLogger('worker')

if c.DEBUG:
    l.setLevel(logging.DEBUG)
else:
    l.setLevel(logging.INFO)

# logging.getLogger('sqlalchemy.engine').setLevel(logging.INFO)

l.info("Starting up…")
engine = create_engine(c.SQLALCHEMY_DATABASE_URI)
engine.connect()

try:
    engine.execute('SELECT 1 from bridge')
except exc.SQLAlchemyError as e:
    l.error(e)
    sys.exit()

session = Session(engine)


def check_worker_stop():
    if Path('worker_stop').exists():
        l.info("Worker paused...exiting")
        session.add(worker_stat)
        session.commit()
        session.close()
        exit(0)


check_worker_stop()

bridges = session.query(Bridge).filter_by(enabled=True)

if not c.DEVELOPMENT:
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

    if args.worker != (bridge.id % c.WORKER_JOBS) + 1:
        continue

    mastodon_last_id = bridge.mastodon_last_id
    twitter_last_id = bridge.twitter_last_id

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
            request_timeout=15
    )

    twitter_api = twitter.Api(
            consumer_key=c.TWITTER_CONSUMER_KEY,
            consumer_secret=c.TWITTER_CONSUMER_SECRET,
            access_token_key=bridge.twitter_oauth_token,
            access_token_secret=bridge.twitter_oauth_secret,
            tweet_mode='extended'  # Allow tweets longer than 140 raw characters
    )

    #
    # Fetch from Mastodon
    #

    new_toots: List[Any] = []

    try:
        new_toots = mast_api.account_statuses(
                bridge.mastodon_account_id,
                since_id=bridge.mastodon_last_id
        )
    except MastodonAPIError as e:
        l.error(e)

        if any(x in repr(e) for x in ['revoked', 'invalid', 'not found', 'Forbidden', 'Unauthorized']):
            l.warning(f"Disabling bridge for user {bridge.mastodon_user}@{mastodonhost.hostname}")
            bridge.enabled = False

        continue

    except MastodonNetworkError as e:
        l.error(f"Error with user {bridge.mastodon_user}@{mastodonhost.hostname}: {e}")
        mastodonhost.defer()
        session.commit()

        if c.MAIL_SERVER and c.SEND_DEFERRED_EMAIL:

            try:
                message = f"""From: {c.MAIL_DEFAULT_SENDER}
To: {c.MAIL_TO}
Subject: {mastodonhost.hostname} Deferred

"""
                smtpObj = smtplib.SMTP(c.MAIL_SERVER)
                smtpObj.sendmail(c.MAIL_DEFAULT_SENDER, [c.MAIL_TO], message)

            except smtplib.SMTPException as e:
                l.error(e)

        continue

    if c.SEND and len(new_toots) != 0:
        bridge.mastodon_last_id = int(new_toots[0]['id'])
        bridge.updated = datetime.now()
    new_toots.reverse()

    #
    # Fetch from Twitter
    #

    new_tweets: List[Any] = []

    try:
        new_tweets = twitter_api.GetUserTimeline(
                since_id=bridge.twitter_last_id,
                include_rts=True,
                exclude_replies=False)

    except TwitterError as e:
        l.error(f"Error with on user @{bridge.twitter_handle}: {e}")

        if 'Unknown' in e.message:
            continue
        # elif 'OAuthAccessTokenException' in e.message:
        #     l.warning(f"Disabling bridge for twitter user {bridge.twitter_handle}")
        #     bridge.enabled = False

        elif isinstance(e.message, list) and len(e.message) > 0:
            if e.message[0]['code'] in [89, 326]:
                l.warning(f"Disabling bridge for twitter user {bridge.twitter_handle}")
                bridge.enabled = False

        continue

    except ConnectionError as e:
        continue

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
            l.error(f"Instagram API Error: {e.error_message}")

            if e.error_type is 'OAuthAccessTokenException':
                bridge.instagram_access_code = None
                bridge.instagram_account_id = 0
                bridge.instagram_handle = None
                bridge.updated = datetime.now()
                session.commit()
        except InstagramClientError as e:
            l.error(f"Instagram Client Error: {e.error_message}")
            
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

    l.debug(f"{bridge.id}: M - {bridge.mastodon_user}@{mastodonhost.hostname}")

    if bridge.t_settings.post_to_twitter_enabled and len(new_toots) != 0:
        l.info(f"{len(new_toots)} new toots found")

    tweet_poster = TweetPoster(c.SEND, session, twitter_api, bridge)

    if bridge.t_settings.post_to_twitter_enabled and len(new_toots) > 0:

        for toot in new_toots:

            t = Toot(bridge.t_settings, toot, c)

            result = tweet_poster.post(t)

            if result:
                worker_stat.add_toot()

    #
    # Post Tweets to Mastodon
    #

    l.debug(f"{bridge.id}: T - @{bridge.twitter_handle}")

    if bridge.t_settings.post_to_mastodon_enabled and len(new_tweets) != 0:
        l.info(f"{len(new_tweets)} new tweets found")

    toot_poster = TootPoster(c.SEND, session, mast_api, bridge)

    if bridge.t_settings.post_to_mastodon_enabled and len(new_tweets) > 0:

        for status in new_tweets:

            tweet = Tweet(bridge.t_settings, status, twitter_api)

            result = toot_poster.post(tweet)

            if result:
                worker_stat.add_tweet()

    #
    # Post Instagram
    #

    if len(new_instas) > 0:
        l.debug(f"{bridge.id}: I - {bridge.instagram_handle}")

        if bridge.t_settings.instagram_post_to_mastodon or bridge.t_settings.instagram_post_to_twitter:
            l.info(f"{len(new_toots)} new instas found")

        for data in new_instas:
            stat_recorded = False

            insta = Insta(bridge.t_settings, data)

            if bridge.t_settings.instagram_post_to_mastodon:
                result = toot_poster.post(insta)
                if result:
                    worker_stat.add_insta()
                    stat_recorded = True

            if bridge.t_settings.instagram_post_to_twitter:

                result = tweet_poster.post(insta)
                if result and not stat_recorded:
                    worker_stat.add_insta()

    if c.SEND:
        session.commit()

    end_time = time.time()
    worker_stat.time = end_time - start_time
    bridge_count = bridge_count + 1

    check_worker_stop()

if c.HEALTHCHECKS:
    requests.get(c.HEALTHCHECKS)

l.info(f"-- All done -> Total time: {worker_stat.formatted_time} / {worker_stat.items} items / {bridge_count} Bridges")

session.add(worker_stat)
session.commit()
session.close()
