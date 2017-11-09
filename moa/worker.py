import html
import importlib
import logging
import mimetypes
import os
import re
import tempfile
import time
import requests
import twitter
import pprint as pp
from mastodon import Mastodon
from mastodon.Mastodon import MastodonAPIError
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from helpers import send_tweet
from toot import Toot

from models import Bridge

moa_config = os.environ.get('MOA_CONFIG', 'DevelopmentConfig')
c = getattr(importlib.import_module('config'), moa_config)


MASTODON_RETRIES = 3
MASTODON_RETRY_DELAY = 20

FORMAT = '%(asctime)-15s %(message)s'
logging.basicConfig(format=FORMAT)

l = logging.getLogger('worker')
l.setLevel(logging.INFO)

engine = create_engine(c.SQLALCHEMY_DATABASE_URI)
session = Session(engine)

bridges = session.query(Bridge).filter_by(enabled=True)

for bridge in bridges:
    l.debug(bridge.settings.__dict__)

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
        l.info(f"Mastodon: {bridge.mastodon_user} -> Twitter: {bridge.twitter_handle}")
        new_toots = mast_api.account_statuses(
            bridge.mastodon_account_id,
            since_id=bridge.mastodon_last_id
        )
        if len(new_toots) != 0:
            mastodon_last_id = int(new_toots[0]['id'])
        l.info(f"{len(new_toots)} new toots found")

    if bridge.settings.post_to_mastodon:
        l.info(f"Twitter: {bridge.twitter_handle} -> Mastodon: {bridge.mastodon_user}")
        new_tweets = twitter_api.GetUserTimeline(
            since_id=bridge.twitter_last_id,
            include_rts=False,
            exclude_replies=True)
        if len(new_tweets) != 0:
            twitter_last_id = new_tweets[0].id
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
                for tweet in t.tweet_parts[:-1]:
                    if c.SEND:
                        reply_to = send_tweet(tweet, reply_to, media_ids, twitter_api)

                tweet = t.tweet_parts[-1]

                for attachment in t.attachments:

                    temp_file_read = open(attachment, 'rb')
                    l.info('Uploading ' + attachment)
                    media_ids.append(twitter_api.UploadMediaChunked(media=temp_file_read))
                    temp_file_read.close()
                    os.unlink(attachment)

                if c.SEND:
                    reply_to = send_tweet(tweet, reply_to, media_ids, twitter_api)

                twitter_last_id = reply_to

        bridge.mastodon_last_id = mastodon_last_id
        bridge.twitter_last_id = twitter_last_id

    if bridge.settings.post_to_mastodon:

        if len(new_tweets) != 0:

            new_tweets.reverse()

            # print([s.full_text for s in new_tweets])

            for tweet in new_tweets:

                content = tweet.full_text
                media_attachments = tweet.media
                urls = tweet.urls
                sensitive = bool(tweet.possibly_sensitive)
                l.debug(f"Sensitive {sensitive}")

                twitter_last_id = tweet.id

                content_toot = html.unescape(content)
                mentions = re.findall(r'[@]\S*', content_toot)
                media_ids = []

                if mentions:
                    for mention in mentions:
                        # Replace all mentions for an equivalent to clearly signal their origin on Twitter
                        content_toot = re.sub(mention, f"🐦{mention[1:]}", content_toot)

                if urls:
                    for url in urls:
                        # Unshorten URLs
                        content_toot = re.sub(url.url, url.expanded_url, content_toot)

                if media_attachments:
                    for attachment in media_attachments:
                        # Remove the t.co link to the media
                        content_toot = re.sub(attachment.url, "", content_toot)

                        attachment_url = attachment.media_url

                        l.debug('Downloading ' + attachment_url)
                        attachment_file = requests.get(attachment_url, stream=True)
                        attachment_file.raw.decode_content = True
                        temp_file = tempfile.NamedTemporaryFile(delete=False)
                        temp_file.write(attachment_file.raw.read())
                        temp_file.close()

                        file_extension = mimetypes.guess_extension(attachment_file.headers['Content-type'])
                        upload_file_name = temp_file.name + file_extension
                        os.rename(temp_file.name, upload_file_name)

                        l.debug('Uploading ' + upload_file_name)
                        media_ids.append(mast_api.media_post(upload_file_name))
                        os.unlink(upload_file_name)

                try:
                    retry_counter = 0
                    post_success = False
                    while not post_success:
                        try:
                            # Toot
                            if len(media_ids) == 0:
                                l.info(f'Tooting "{content_toot}"...')
                                post = mast_api.status_post(
                                    content_toot,
                                    visibility=bridge.settings.toot_visibility,
                                    sensitive=sensitive)

                                mastodon_last_id = post["id"]
                                post_success = True
                            else:
                                l.info(f'Tooting "{content_toot}", with attachments...')
                                post = mast_api.status_post(
                                    content_toot,
                                    media_ids=media_ids,
                                    visibility=bridge.settings.toot_visibility,
                                    sensitive=sensitive)

                                mastodon_last_id = post["id"]
                                post_success = True

                        except MastodonAPIError:
                            if retry_counter < MASTODON_RETRIES:
                                retry_counter += 1
                                time.sleep(MASTODON_RETRY_DELAY)
                            else:
                                raise MastodonAPIError

                except MastodonAPIError:
                    l.error("Encountered error after " + str(MASTODON_RETRIES) + " retries. Not retrying.")

            bridge.mastodon_last_id = mastodon_last_id
            bridge.twitter_last_id = twitter_last_id

    if c.SEND:
        session.commit()

session.close()
