import importlib
import logging
import os
import sys
import time
from typing import List, Any

import requests
import twitter
from instagram import InstagramAPI, InstagramClientError, InstagramAPIError
from instagram.helper import datetime_to_timestamp
from mastodon import Mastodon
from mastodon.Mastodon import MastodonAPIError, MastodonNetworkError
from requests import ConnectionError
from sqlalchemy import create_engine, exc
from sqlalchemy.orm import Session
from sqlalchemy.sql.expression import func
from twitter import TwitterError

from moa.insta import Insta
from moa.models import Bridge, WorkerStat
from moa.toot import Toot
from moa.tweet import Tweet
from moa.tweet_poster import TweetPoster
from moa.toot_poster import TootPoster

start_time = time.time()
worker_stat = WorkerStat()

moa_config = os.environ.get('MOA_CONFIG', 'DevelopmentConfig')
c = getattr(importlib.import_module('config'), moa_config)

if c.SENTRY_DSN:
    from raven import Client

    client = Client(c.SENTRY_DSN)

FORMAT = "%(asctime)-15s [%(filename)s:%(lineno)s : %(funcName)s()] %(message)s"

logging.basicConfig(format=FORMAT)

l = logging.getLogger('worker')
l.setLevel(logging.DEBUG)

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

bridges = session.query(Bridge).filter_by(enabled=True)

if not c.DEBUG:
    bridges = bridges.order_by(func.rand())

for bridge in bridges:
    # l.debug(bridge.settings.__dict__)

    total_time = time.time() - start_time

    if total_time > 60 * 4.5:
        continue

    mastodon_last_id = bridge.mastodon_last_id
    twitter_last_id = bridge.twitter_last_id

    mastodonhost = bridge.mastodon_host

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
    # l.error(f"-- {bridge.mastodon_user}@{mastodonhost.hostname} --")

    try:
        new_toots = mast_api.account_statuses(
                bridge.mastodon_account_id,
                since_id=bridge.mastodon_last_id
        )
    except MastodonAPIError as e:
        l.error(e)

        if any(x in repr(e) for x in ['revoked', 'invalid', 'not found', 'Forbidden']):
            l.warning(f"Disabling bridge for user {bridge.mastodon_user}@{mastodonhost.hostname}")
            bridge.enabled = False

        continue

    except MastodonNetworkError as e:
        # l.error(f"Working on user {bridge.mastodon_user}@{mastodonhost.hostname}")
        l.error(e)
        continue

    if bridge.settings.post_to_twitter_enabled and len(new_toots) != 0:
        l.info(f"Mastodon: {bridge.mastodon_user} {mastodon_last_id} -> Twitter: {bridge.twitter_handle}")
        l.info(f"{len(new_toots)} new toots found")

    if c.SEND and len(new_toots) != 0:
        bridge.mastodon_last_id = int(new_toots[0]['id'])
    new_toots.reverse()

    #
    # Fetch from Twitter
    #

    new_tweets: List[Any] = []
    # l.error(f"-- @{bridge.twitter_handle} --")

    try:
        new_tweets = twitter_api.GetUserTimeline(
                since_id=bridge.twitter_last_id,
                include_rts=True,
                exclude_replies=False)

    except TwitterError as e:
        l.error(e)

        if 'Unknown' in e.message:
            continue
        # elif 'OAuthAccessTokenException' in e.message:
        #     l.warning(f"Disabling bridge for twitter user {bridge.twitter_handle}")
        #     bridge.enabled = False

        elif isinstance(e.message, list) and len(e.message) > 0:
            if e.message[0]['code'] in [89]:
                l.warning(f"Disabling bridge for twitter user {bridge.twitter_handle}")
                bridge.enabled = False

        continue

    except ConnectionError as e:
        continue

    if bridge.settings.post_to_mastodon_enabled and len(new_tweets) != 0:
        l.info(f"Twitter: {bridge.twitter_handle} {twitter_last_id} -> Mastodon: {bridge.mastodon_user}")
        l.info(f"{len(new_tweets)} new tweets found")

    if c.SEND and len(new_tweets) != 0:
        bridge.twitter_last_id = new_tweets[0].id
    new_tweets.reverse()

    #
    # Instagram
    #

    new_instas = []

    if bridge.instagram_access_code:

        # l.error(f"-- INSTAGRAM: {bridge.instagram_account_id} --")

        api = InstagramAPI(access_token=bridge.instagram_access_code, client_secret=c.INSTAGRAM_SECRET)

        try:
            recent_media, _ = api.user_recent_media(user_id=bridge.instagram_account_id)
        except Exception as e:
            l.error(e)
            continue

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

    tweet_poster = TweetPoster(c.SEND, session, twitter_api, bridge)

    if bridge.settings.post_to_twitter_enabled and len(new_toots) > 0:

        for toot in new_toots:

            t = Toot(bridge.settings, toot, c)

            result = tweet_poster.post(t)

            if result:
                worker_stat.add_toot()

    #
    # Post Tweets to Mastodon
    #

    toot_poster = TootPoster(c.SEND, session, mast_api, bridge)

    if bridge.settings.post_to_mastodon_enabled and len(new_tweets) > 0:

        for status in new_tweets:

            tweet = Tweet(bridge.settings, status, twitter_api)

            result = toot_poster.post(tweet)

            if result:
                worker_stat.add_tweet()

    #
    # Post Instagram
    #

    if len(new_instas) > 0:

        for data in new_instas:
            stat_recorded = False

            insta = Insta(bridge.settings, data)

            if bridge.settings.instagram_post_to_mastodon:
                result = toot_poster.post(insta)
                if result:
                    worker_stat.add_insta()
                    stat_recorded = True

            if bridge.settings.instagram_post_to_twitter:

                result = tweet_poster.post(insta)
                if result and not stat_recorded:
                    worker_stat.add_insta()

    if c.SEND:
        session.commit()

if c.HEALTHCHECKS:
    requests.get(c.HEALTHCHECKS)

end_time = time.time()
worker_stat.time = end_time - start_time

l.info(
        f"-- All done -> Total time: {worker_stat.formatted_time} / {worker_stat.items} items / {worker_stat.avg}s avg")

session.add(worker_stat)
session.commit()
session.close()
