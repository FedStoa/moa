import html
import logging
import mimetypes
import os
import re
import tempfile

import requests
import time
import twitter
from mastodon import Mastodon
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app import mastodon_api
from config import DevelopmentConfig
from models import Bridge

MASTODON_RETRIES = 3
TWITTER_RETRIES = 3
MASTODON_RETRY_DELAY = 20
TWITTER_RETRY_DELAY = 20

FORMAT = '%(asctime)-15s %(message)s'
logging.basicConfig(format=FORMAT)

l = logging.getLogger()
l.setLevel(logging.INFO)
c = DevelopmentConfig()

engine = create_engine(c.DATABASE_URI)
session = Session(engine)

bridges = session.query(Bridge).filter_by(enabled=True)

for bridge in bridges:
    l.info(bridge.settings.__dict__)

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

    if bridge.settings.post_to_mastodon:
        l.info(f"Twitter: {bridge.twitter_handle} -> Mastodon: {bridge.mastodon_user}")

        new_tweets = twitter_api.GetUserTimeline(
            since_id=bridge.twitter_last_id,
            include_rts=False,
            exclude_replies=True)

        if len(new_tweets) != 0:
            l.info(f"{len(new_tweets)} new tweets found")

            new_tweets.reverse()

            print([s.full_text for s in new_tweets])

            for tweet in new_tweets:

                content = tweet.full_text
                media_attachments = tweet.media
                urls = tweet.urls
                sensitive = tweet.possibly_sensitive

                content_toot = html.unescape(content)
                mentions = re.findall(r'[@]\S*', content_toot)
                media_ids = []

                if mentions:
                    for mention in mentions:
                        # Replace all mentions for an equivalent to clearly signal their origin on Twitter
                        content_toot = re.sub(mention, mention + '@🐦', content_toot)

                if urls:
                    for url in urls:
                        # Unshorten URLs
                        content_toot = re.sub(url.url, url.expanded_url, content_toot)

                if media_attachments:
                    for attachment in media_attachments:
                        # Remove the t.co link to the media
                        content_toot = re.sub(attachment.url, "", content_toot)

                        attachment_url = attachment.media_url

                        l.info('Downloading ' + attachment_url)
                        attachment_file = requests.get(attachment_url, stream=True)
                        attachment_file.raw.decode_content = True
                        temp_file = tempfile.NamedTemporaryFile(delete=False)
                        temp_file.write(attachment_file.raw.read())
                        temp_file.close()

                        file_extension = mimetypes.guess_extension(attachment_file.headers['Content-type'])
                        upload_file_name = temp_file.name + file_extension
                        os.rename(temp_file.name, upload_file_name)

                        print('Uploading ' + upload_file_name)
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
                                    visibility=bridge.settings.toot_visibility)
                                since_toot_id = post["id"]
                                post_success = True
                            else:
                                l.info(f'Tooting "{content_toot}", with attachments...')
                                post = mast_api.status_post(
                                    content_toot,
                                    media_ids=media_ids,
                                    visibility=bridge.settings.toot_visibility,
                                    sensitive=None)
                                since_toot_id = post["id"]
                                post_success = True
                        except:
                            if retry_counter < TWITTER_RETRIES:
                                retry_counter += 1
                                time.sleep(TWITTER_RETRY_DELAY)
                            else:
                                raise
                except:
                    print("Encountered error after " + str(TWITTER_RETRIES) + " retries. Not retrying.")

session.close()
