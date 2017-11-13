import importlib
import logging
import os
import pprint as pp

import requests
import twitter
from mastodon import Mastodon
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from moa.helpers import send_tweet, send_toot
from moa.models import Bridge, Mapping
from moa.toot import Toot
from moa.tweet import Tweet

moa_config = os.environ.get('MOA_CONFIG', 'DevelopmentConfig')
c = getattr(importlib.import_module('config'), moa_config)

if c.SENTRY_DSN:
    from raven import Client

    client = Client(c.SENTRY_DSN)

FORMAT = '%(asctime)-15s %(message)s'
logging.basicConfig(format=FORMAT)

l = logging.getLogger('worker')
l.setLevel(logging.DEBUG)

l.info("Starting up…")
engine = create_engine(c.SQLALCHEMY_DATABASE_URI)
session = Session(engine)

bridges = session.query(Bridge).filter_by(enabled=True)

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
        debug_requests=False
    )

    twitter_api = twitter.Api(
        consumer_key=c.TWITTER_CONSUMER_KEY,
        consumer_secret=c.TWITTER_CONSUMER_SECRET,
        access_token_key=bridge.twitter_oauth_token,
        access_token_secret=bridge.twitter_oauth_secret,
        tweet_mode='extended'  # Allow tweets longer than 140 raw characters
    )

    if bridge.settings.post_to_twitter:
        new_toots = mast_api.account_statuses(
            bridge.mastodon_account_id,
            since_id=bridge.mastodon_last_id
        )
        if len(new_toots) != 0:
            l.info(f"Mastodon: {bridge.mastodon_user} {mastodon_last_id} -> Twitter: {bridge.twitter_handle}")
            l.info(f"{len(new_toots)} new toots found")

            if c.SEND:
                bridge.mastodon_last_id = int(new_toots[0]['id'])

    if bridge.settings.post_to_mastodon:
        new_tweets = twitter_api.GetUserTimeline(
            since_id=bridge.twitter_last_id,
            include_rts=True,
            exclude_replies=False)
        if len(new_tweets) != 0:
            l.info(f"Twitter: {bridge.twitter_handle} {twitter_last_id} -> Mastodon: {bridge.mastodon_user}")
            l.info(f"{len(new_tweets)} new tweets found")

            if c.SEND:
                bridge.twitter_last_id = new_tweets[0].id

    if bridge.settings.post_to_twitter and len(new_toots) != 0:
        new_toots.reverse()

        url_length = max(twitter_api.GetShortUrlLength(False), twitter_api.GetShortUrlLength(True)) + 1
        l.debug(f"URL length: {url_length}")

        for toot in new_toots:

            t = Toot(toot, bridge.settings, twitter_api)
            t.url_length = url_length

            l.info(f"Working on toot {t.id}")

            # l.debug(pp.pformat(toot))

            if t.should_skip:
                continue

            t.split_toot()

            if c.SEND:
                t.transfer_attachments()

            reply_to = None
            media_ids = []

            if t.is_self_reply:

                # In the case where a toot has been broken into multiple tweets
                # we want the last one posted
                mapping = session.query(Mapping).filter_by(mastodon_id=t.in_reply_to_id).order_by(
                    Mapping.created.desc()
                ).first()

                if mapping:
                    reply_to = mapping.twitter_id
                    l.info(f"Replying to twitter status {reply_to} / masto status {t.in_reply_to_id}")

            # Do normal posting for all but the last tweet where we need to upload media
            for status in t.tweet_parts[:-1]:
                if c.SEND:
                    reply_to = send_tweet(status, reply_to, None, twitter_api)

                    if reply_to:
                        m = Mapping()
                        m.mastodon_id = t.id
                        m.twitter_id = reply_to
                        session.add(m)

                        bridge.mastodon_last_id = t.id

                        session.commit()

            status = t.tweet_parts[-1]

            if c.SEND:
                twitter_last_id = send_tweet(status, reply_to, media_ids, twitter_api)

                if twitter_last_id:
                    m = Mapping()
                    m.mastodon_id = t.id
                    m.twitter_id = reply_to
                    session.add(m)

                    bridge.twitter_last_id = twitter_last_id

                bridge.mastodon_last_id = t.id
                session.commit()

    if bridge.settings.post_to_mastodon and len(new_tweets) != 0:

        new_tweets.reverse()

        for status in new_tweets:

            l.info(f"Working on tweet {status.id}")

            l.debug(pp.pformat(status.__dict__))

            tweet = Tweet(status, bridge.settings, twitter_api, mast_api)

            if tweet.should_skip:
                continue

            if c.SEND:
                tweet.transfer_attachments()

            reply_to = None
            if tweet.is_self_reply:
                mapping = session.query(Mapping).filter_by(twitter_id=status.in_reply_to_status_id).first()

                if mapping:
                    reply_to = mapping.mastodon_id
                    l.info(f"Replying to mastodon status {reply_to}")

            if c.SEND:
                mastodon_last_id = send_toot(tweet,
                                             bridge.settings,
                                             mast_api,
                                             reply_to=reply_to)

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

    if c.SEND:
        session.commit()

session.close()
l.info("All done")

if c.HEALTHCHECKS:
    requests.get(c.HEALTHCHECKS)
