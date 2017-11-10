import importlib
import logging
import os
import pprint as pp

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
l.setLevel(logging.INFO)

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
            mastodon_last_id = int(new_toots[0]['id'])
            l.info(f"Mastodon: {bridge.mastodon_user} -> Twitter: {bridge.twitter_handle}")
            l.info(f"{len(new_toots)} new toots found")

    if bridge.settings.post_to_mastodon:
        new_tweets = twitter_api.GetUserTimeline(
            since_id=bridge.twitter_last_id,
            include_rts=True,
            exclude_replies=False)
        if len(new_tweets) != 0:
            twitter_last_id = new_tweets[0].id
            l.info(f"Twitter: {bridge.twitter_handle} -> Mastodon: {bridge.mastodon_user}")
            l.info(f"{len(new_tweets)} new tweets found")

    if bridge.settings.post_to_twitter:
        if len(new_toots) != 0:
            new_toots.reverse()

            url_length = max(twitter_api.GetShortUrlLength(False), twitter_api.GetShortUrlLength(True)) + 1
            l.debug(f"URL length: {url_length}")

            for toot in new_toots:

                t = Toot(toot, bridge.settings)
                t.url_length = url_length

                l.info(f"Working on toot {t.id}")

                l.debug(pp.pformat(toot))

                if t.should_skip:
                    continue

                t.split_toot()
                if c.SEND:
                    t.download_attachments()

                reply_to = None
                media_ids = []

                # Do normal posting for all but the last tweet where we need to upload media
                for status in t.tweet_parts[:-1]:
                    if c.SEND:
                        reply_to = send_tweet(status, reply_to, media_ids, twitter_api)

                        if reply_to != 0:
                            m = Mapping()
                            m.mastodon_id = t.id
                            m.twitter_id = reply_to
                            session.add(m)

                status = t.tweet_parts[-1]

                for attachment in t.attachments:

                    file = attachment[0]
                    description = attachment[1]

                    temp_file_read = open(file, 'rb')
                    l.info(f'Uploading {description} {file}')
                    media_id = twitter_api.UploadMediaChunked(media=temp_file_read)

                    if description:
                        twitter_api.PostMediaMetadata(media_id, alt_text=description)

                    media_ids.append(media_id)
                    temp_file_read.close()
                    os.unlink(file)

                if c.SEND:
                    reply_to = send_tweet(status, reply_to, media_ids, twitter_api)

                    if reply_to != 0:
                        m = Mapping()
                        m.mastodon_id = t.id
                        m.twitter_id = reply_to
                        session.add(m)

                twitter_last_id = reply_to

        bridge.mastodon_last_id = mastodon_last_id
        bridge.twitter_last_id = twitter_last_id

    if bridge.settings.post_to_mastodon:

        if len(new_tweets) != 0:

            new_tweets.reverse()

            for status in new_tweets:

                l.info(f"Working on tweet {status.id}")

                l.debug(pp.pformat(status.__dict__))

                tweet = Tweet(status, bridge.settings, twitter_api, mast_api)

                l.debug(tweet.clean_content)

                if tweet.should_skip:
                    continue

                if c.SEND:
                    tweet.transfer_attachments()

                twitter_last_id = status.id

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

                    if mastodon_last_id != 0:
                        m = Mapping()
                        m.mastodon_id = mastodon_last_id
                        m.twitter_id = status.id
                        session.add(m)

            bridge.mastodon_last_id = mastodon_last_id
            bridge.twitter_last_id = twitter_last_id

    if c.SEND:
        session.commit()

session.close()
l.info("All done")
