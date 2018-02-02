import importlib
import logging
import os
import pprint as pp
import sys
import time

import requests
import twitter
from instagram import InstagramAPI
from instagram.helper import datetime_to_timestamp
from mastodon import Mastodon
from mastodon.Mastodon import MastodonAPIError, MastodonNetworkError
from requests import ConnectionError
from sqlalchemy import create_engine, exc
from sqlalchemy.orm import Session
from sqlalchemy.sql.expression import func
from twitter import TwitterError

from moa.models import Bridge, Mapping, WorkerStat
from moa.twitter_poster import TwitterPoster
from moa.toot import Toot
from moa.tweet import Tweet

start_time = time.time()
worker_stat = WorkerStat()

moa_config = os.environ.get('MOA_CONFIG', 'DevelopmentConfig')
c = getattr(importlib.import_module('config'), moa_config)

if c.SENTRY_DSN:
    from raven import Client

    client = Client(c.SENTRY_DSN)

FORMAT = '%(asctime)-15s %(message)s'
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

    new_toots = []

    try:
        new_toots = mast_api.account_statuses(
                bridge.mastodon_account_id,
                since_id=bridge.mastodon_last_id
        )
    except MastodonAPIError as e:
        l.error(f"Working on user {bridge.mastodon_user}@{mastodonhost.hostname}")
        l.error(e)

        if any(x in repr(e) for x in ['revoked', 'invalid', 'not found']):
            l.warning(f"Disabling bridge for user {bridge.mastodon_user}@{mastodonhost.hostname}")
            bridge.enabled = False

        continue

    except MastodonNetworkError as e:
        l.error(f"Working on user {bridge.mastodon_user}@{mastodonhost.hostname}")
        l.error(e)
        continue

    if bridge.settings.post_to_twitter_enabled and len(new_toots) != 0:
        l.info(f"Mastodon: {bridge.mastodon_user} {mastodon_last_id} -> Twitter: {bridge.twitter_handle}")
        l.info(f"{len(new_toots)} new toots found")

    if c.SEND and len(new_toots) != 0:
        bridge.mastodon_last_id = int(new_toots[0]['id'])

    #
    # Fetch from Twitter
    #

    new_tweets = []
    try:
        new_tweets = twitter_api.GetUserTimeline(
                since_id=bridge.twitter_last_id,
                include_rts=True,
                exclude_replies=False)

    except TwitterError as e:
        l.error(f"Working on twitter user {bridge.twitter_handle}")
        l.error(e)

        if len(e.message) > 0:
            if e.message[0]['code'] == 89:
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

    #
    # Instagram
    #

    new_instas = []

    if bridge.instagram_access_code:
        api = InstagramAPI(access_token=bridge.instagram_access_code, client_secret=c.INSTAGRAM_SECRET)

        recent_media, _ = api.user_recent_media(user_id=bridge.instagram_account_id)

        for media in recent_media:

            ts = datetime_to_timestamp(media.created_time)

            if ts > bridge.instagram_last_id:
                new_instas.append(media)

        if c.SEND and len(new_instas) != 0:
            bridge.instagram_last_id = datetime_to_timestamp(new_toots[0].created_time)
            new_instas.reverse()



    #
    # Post to Twitter
    #

    if bridge.settings.post_to_twitter_enabled and len(new_toots) != 0:
        new_toots.reverse()

        poster = TwitterPoster(c.SEND, session, twitter_api, bridge)

        for toot in new_toots:

            t = Toot(toot, bridge.settings)

            result = poster.post_toot(t)

            if result:
                worker_stat.add_toot()


    #
    # Post to Mastodon
    #

    if bridge.settings.post_to_mastodon_enabled and len(new_tweets) != 0:

        new_tweets.reverse()

        for status in new_tweets:

            l.info(f"Working on tweet {status.id}")

            tweet = Tweet(status, bridge.settings, twitter_api, mast_api)

            worker_stat.add_tweet()

            if tweet.should_skip:
                continue

            l.debug(pp.pformat(status.__dict__))

            if c.SEND:
                if not tweet.transfer_attachments():
                    continue

            reply_to = None
            if tweet.is_self_reply:
                mapping = session.query(Mapping).filter_by(twitter_id=status.in_reply_to_status_id).first()

                if mapping:
                    reply_to = mapping.mastodon_id
                    l.info(f"Replying to mastodon status {reply_to}")

            if c.SEND:
                mastodon_last_id = tweet.send_toot(reply_to=reply_to)
                l.info(f"Toot ID: {mastodon_last_id}")

                if mastodon_last_id:
                    m = Mapping()
                    m.mastodon_id = mastodon_last_id
                    m.twitter_id = status.id
                    session.add(m)

                    bridge.mastodon_last_id = mastodon_last_id

                bridge.twitter_last_id = status.id
                session.commit()

            else:
                l.info(tweet.clean_content)

    if len(new_instas) > 0 and bridge.settings.instagram_post_to_mastodon:

        for insta in new_instas:

            l.info(f"Working on insta {insta.id}")

    if c.SEND:
        session.commit()

if c.HEALTHCHECKS:
    requests.get(c.HEALTHCHECKS)

end_time = time.time()
worker_stat.time = end_time - start_time

l.info(
    f"----------- All done -> Total time: {worker_stat.formatted_time} / {worker_stat.items} items / {worker_stat.avg}s avg -------------")

session.add(worker_stat)
session.commit()
session.close()
