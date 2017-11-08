import html
import logging
import mimetypes
import os
import re
import tempfile
import time

import requests
import twitter
from mastodon import Mastodon
from mastodon.Mastodon import MastodonAPIError
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from twitter import twitter_utils, TwitterError

from config import DevelopmentConfig
from models import Bridge

#
# Lot's of code lifted from https://github.com/halcy/MastodonToTwitter
#

MASTODON_RETRIES = 3
TWITTER_RETRIES = 3
MASTODON_RETRY_DELAY = 20
TWITTER_RETRY_DELAY = 20

# Some helpers copied out from python-twitter, because they're broken there
URL_REGEXP = re.compile((
                            r'('
                            r'(?!(https?://|www\.)?\.|ftps?://|([0-9]+\.){{1,3}}\d+)'  # exclude urls that start with "."
                            r'(?:https?://|www\.)*(?!.*@)(?:[\w+-_]+[.])'  # beginning of url
                            r'(?:{0}\b|'  # all tlds
                            r'(?:[:0-9]))'  # port numbers & close off TLDs
                            r'(?:[\w+\/]?[a-z0-9!\*\'\(\);:&=\+\$/%#\[\]\-_\.,~?])*'  # path/query params
                            r')').format(r'\b|'.join(twitter_utils.TLDS)), re.U | re.I | re.X)


def calc_expected_status_length(status, short_url_length=23):
    replaced_chars = 0
    status_length = len(status)
    match = re.findall(URL_REGEXP, status)
    if len(match) >= 1:
        replaced_chars = len(''.join(map(lambda x: x[0], match)))
        status_length = status_length - replaced_chars + (short_url_length * len(match))
    return status_length


FORMAT = '%(asctime)-15s %(message)s'
logging.basicConfig(format=FORMAT)

l = logging.getLogger('worker')
l.setLevel(logging.INFO)
c = DevelopmentConfig()

engine = create_engine(c.SQLALCHEMY_DATABASE_URI)
session = Session(engine)

bridges = session.query(Bridge).filter_by(enabled=True)

for bridge in bridges:
    l.info(bridge.settings.__dict__)

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
            # print([s.full_text for s in new_toots])

            MEDIA_REGEXP = re.compile("https://" +
                re.escape(mastodonhost.hostname) + "\/media\/[\w-]+\s?")
            url_length = max(twitter_api.GetShortUrlLength(False), twitter_api.GetShortUrlLength(True)) + 1
            l.debug(f"URL length: {url_length}")

            for toot in new_toots:
                content = toot["content"]
                media_attachments = toot["media_attachments"]

                l.info(f"Working on toot {toot['id']}")

                # We trust mastodon to return valid HTML
                content_clean = re.sub(r'<a [^>]*href="([^"]+)">[^<]*</a>', '\g<1>', content)

                # We replace html br with new lines
                content_clean = "\n".join(re.compile(r'<br ?/?>', re.IGNORECASE).split(content_clean))

                # We must also replace new paragraphs with double line skips
                content_clean = "\n\n".join(re.compile(r'</p><p>', re.IGNORECASE).split(content_clean))

                # Then we can delete the other html contents and unescape the string
                content_clean = html.unescape(str(re.compile(r'<.*?>').sub("", content_clean).strip()))

                # Trim out media URLs
                content_clean = re.sub(MEDIA_REGEXP, "", content_clean)

                content_clean = content_clean.strip()

                # Don't cross-post replies
                if len(content_clean) != 0 and content_clean[0] == '@':
                    l.info(f'Skipping toot "{content_clean}" - is a reply.')
                    continue

                # Split toots, if need be, using Many magic numbers.
                content_parts = []
                if calc_expected_status_length(content_clean, short_url_length=url_length) > 140:
                    l.info('Toot bigger 140 characters, need to split...')
                    current_part = ""
                    for next_word in content_clean.split(" "):
                        # Need to split here?
                        if calc_expected_status_length(f"{current_part} {next_word}",
                                                       short_url_length=url_length) > 135:
                            # print("new part")
                            space_left = 135 - calc_expected_status_length(current_part,
                                                                           short_url_length=url_length) - 1

                            if bridge.settings.split_twitter_messages:
                                # Want to split word?
                                if len(next_word) > 30 and space_left > 5 and not twitter.twitter_utils.is_url(
                                        next_word):
                                    current_part = f"{current_part} {next_word[:space_left]}"
                                    content_parts.append(current_part)
                                    current_part = next_word[space_left:]
                                else:
                                    content_parts.append(current_part)
                                    current_part = next_word

                                # Split potential overlong word in current_part
                                while len(current_part) > 135:
                                    content_parts.append(current_part[:135])
                                    current_part = current_part[135:]
                            else:
                                l.info('In fact we just cut')
                                space_for_suffix = len('… ') + url_length
                                content_parts.append(f"{current_part[:-space_for_suffix]}… {toot['url']}")
                                current_part = ''
                                break
                        else:
                            # Just plop next word on
                            current_part = f"{current_part} {next_word}"
                    # Insert last part
                    if len(current_part.strip()) != 0 or len(content_parts) == 0:
                        content_parts.append(current_part.strip())

                else:
                    l.info('Toot < 140 chars, posting directly...')
                    content_parts.append(content_clean)

                # Tweet all the parts. On error, give up and go on with the next toot.
                try:
                    reply_to = None
                    for i in range(len(content_parts)):
                        media_ids = []
                        content_tweet = content_parts[i]
                        if bridge.settings.split_twitter_messages:
                            content_tweet += "…"

                        # Last content part: Upload media, no -- at the end
                        if i == len(content_parts) - 1:
                            for attachment in media_attachments:
                                attachment_url = attachment["url"]

                                l.info('Downloading ' + attachment_url)
                                attachment_file = requests.get(attachment_url, stream=True)
                                attachment_file.raw.decode_content = True
                                temp_file = tempfile.NamedTemporaryFile(delete=False)
                                temp_file.write(attachment_file.raw.read())
                                temp_file.close()

                                file_extension = mimetypes.guess_extension(attachment_file.headers['Content-type'])
                                upload_file_name = temp_file.name + file_extension
                                os.rename(temp_file.name, upload_file_name)

                                temp_file_read = open(upload_file_name, 'rb')
                                l.info('Uploading ' + upload_file_name)
                                media_ids.append(twitter_api.UploadMediaChunked(media=temp_file_read))
                                temp_file_read.close()
                                os.unlink(upload_file_name)

                            content_tweet = content_parts[i]

                        # Some final cleaning
                        content_tweet = content_tweet.strip()

                        # Retry three times before giving up
                        retry_counter = 0
                        post_success = False
                        while not post_success:
                            try:
                                # Tweet
                                if len(media_ids) == 0:
                                    l.info(f'Tweeting "{content_tweet}"')
                                    reply_to = twitter_api.PostUpdate(content_tweet, in_reply_to_status_id=reply_to).id
                                    twitter_last_id = reply_to
                                    post_success = True
                                else:
                                    l.info(f'Tweeting "{content_tweet}", with attachments')
                                    reply_to = twitter_api.PostUpdate(content_tweet,
                                                                      media=media_ids,
                                                                      in_reply_to_status_id=reply_to).id
                                    twitter_last_id = reply_to
                                    post_success = True
                            except TwitterError as e:
                                l.error(e.message)
                                if retry_counter < TWITTER_RETRIES:
                                    retry_counter += 1
                                    time.sleep(TWITTER_RETRY_DELAY)
                                else:
                                    raise
                except:
                    l.error(f"Encountered error after {TWITTER_RETRIES} retries. Not retrying.")

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
                l.info(f"Sensitive {sensitive}")

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

                        l.info('Downloading ' + attachment_url)
                        attachment_file = requests.get(attachment_url, stream=True)
                        attachment_file.raw.decode_content = True
                        temp_file = tempfile.NamedTemporaryFile(delete=False)
                        temp_file.write(attachment_file.raw.read())
                        temp_file.close()

                        file_extension = mimetypes.guess_extension(attachment_file.headers['Content-type'])
                        upload_file_name = temp_file.name + file_extension
                        os.rename(temp_file.name, upload_file_name)

                        l.info('Uploading ' + upload_file_name)
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
                            if retry_counter < TWITTER_RETRIES:
                                retry_counter += 1
                                time.sleep(TWITTER_RETRY_DELAY)
                            else:
                                raise MastodonAPIError

                except MastodonAPIError:
                    l.error("Encountered error after " + str(TWITTER_RETRIES) + " retries. Not retrying.")

            bridge.mastodon_last_id = mastodon_last_id
            bridge.twitter_last_id = twitter_last_id

    session.commit()

session.close()
