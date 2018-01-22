import html
import logging
import mimetypes
import os
import re
import tempfile
import time
from os.path import splitext
from urllib.parse import urlparse

import requests
from mastodon.Mastodon import MastodonAPIError, MastodonNetworkError

logger = logging.getLogger('worker')
MASTODON_RETRIES = 3
MASTODON_RETRY_DELAY = 5


class Tweet:
    def __init__(self, status, settings, api, masto_api):

        self.media_ids = []
        self.attachments = []
        self.__fetched_attachments = None
        self.__content = None
        self.status = status
        self.settings = settings
        self.api = api
        self.masto_api = masto_api

    @property
    def media(self):

        if not self.__fetched_attachments:

            if self.is_retweet:
                target_id = self.status.retweeted_status.id

            elif self.is_quoted:
                target_id = self.status.quoted_status.id
            else:
                target_id = self.status.id

            fetched_tweet = self.api.GetStatus(
                status_id=target_id,
                trim_user=True,
                include_my_retweet=False,
                include_entities=True,
                include_ext_alt_text=True
            )

            self.__fetched_attachments = fetched_tweet.media

            if not self.__fetched_attachments:
                self.__fetched_attachments = []

        return self.__fetched_attachments

    @property
    def should_skip(self):

        if self.is_reply:
            logger.info(f'Skipping reply.')
            return True

        if self.is_retweet and not self.settings.post_rts_to_mastodon:
            logger.info(f'Skipping retweet.')
            return True

        elif self.is_retweet and self.settings.post_rts_to_mastodon:
            # Posting retweets
            pass

        elif not self.settings.post_to_mastodon:
            logger.info(f'Skipping regular tweets.')
            return True

        return False

    @property
    def url(self):
        base = "https://twitter.com"
        user = self.status.user.screen_name
        status = self.status.id

        if self.is_retweet:
            user = self.status.retweeted_status.user.screen_name
            status = self.status.retweeted_status.id

        elif self.is_quoted:
            user = self.status.quoted_status.user.screen_name
            status = self.status.quoted_status.id

        return f"{base}/{user}/status/{status}"

    @property
    def is_retweet(self):
        return self.status.retweeted

    @property
    def is_quoted(self):
        return self.status.quoted_status

    @property
    def is_reply(self):

        if self.status.in_reply_to_screen_name is not None:

            if not self.is_self_reply or self.status.full_text[0] == '@':
                return True

    @property
    def is_self_reply(self):
        return self.status.in_reply_to_user_id == self.status.user.id

    @property
    def urls(self):
        if self.is_retweet:
            return self.status.retweeted_status.urls
        elif self.is_quoted:
            return self.status.quoted_status.urls
        else:
            return self.status.urls

    @property
    def sensitive(self):
        return bool(self.status.possibly_sensitive)

    @property
    def mentions(self):

        m = [u.screen_name for u in self.status.user_mentions]

        m = list(set(m))

        return m

    def expand_handles(self, content):

        if content:
            # mentions = re.findall(r'[@][a-zA-Z0-9_]*', content)

            if self.mentions:
                for mention in self.mentions:
                    # Replace all mentions for an equivalent to clearly signal their origin on Twitter
                    content = re.sub(f"@{mention}", f"@{mention}@twitter.com", content)

        return content

    @property
    def clean_content(self):

        quoted_text = None

        if not self.__content:

            if self.is_retweet:
                content = self.status.retweeted_status.full_text

            elif self.is_quoted:

                content = re.sub(r'https?://.*', '', self.status.full_text, flags=re.MULTILINE)
                quoted_text = f"{self.status.quoted_status.full_text}"

                for url in self.status.quoted_status.urls:
                    # Unshorten URLs
                    quoted_text = re.sub(url.url, url.expanded_url, quoted_text)

            else:
                content = self.status.full_text

            content = html.unescape(content)

            content = self.expand_handles(content)
            quoted_text = self.expand_handles(quoted_text)

            for url in self.urls:
                # Unshorten URLs
                content = re.sub(url.url, url.expanded_url, content)

            if self.is_retweet:
                if len(content) > 0:
                    content = f"RT @{self.status.retweeted_status.user.screen_name}@twitter.com\n{content}"
                else:
                    content = f"RT @{self.status.retweeted_status.user.screen_name}@twitter.com\n"

            elif self.is_quoted:
                possible_content = f"{content}\n---\n{quoted_text}\n{self.url}"

                if len(possible_content) > 500:
                    logger.info(f"Toot is too long: {len(possible_content)}")
                    diff = len(possible_content) - 500 + 1
                    quoted_text = quoted_text[:-diff]
                    content = f"{content}\n\n{quoted_text}…\n{self.url}"
                    logger.info(f"Length is now: {len(content)}")

                else:
                    content = possible_content

            for attachment in self.media:
                # Remove the t.co link to the media
                content = re.sub(attachment.url, "", content)

            if len(content) == 0:
                logger.info("Content is empty - adding unicode character.")
                content = u"\u2063"

            self.__content = content
        return self.__content

    def transfer_attachments(self):

        for attachment in self.media:
            # logger.debug(attachment.__dict__)

            type = attachment.type
            attachment_url = None

            if type in ['video', 'animated_gif']:

                variants = attachment.video_info['variants'].copy()
                variants.reverse()

                # logger.debug(variants)

                index = 0
                max = len(variants) - 1

                while not attachment_url:
                    logger.info(f"Examining attachment variant {index}")

                    if not variants[index].get('bitrate', None):
                        attachment_url = None
                        index += 1

                        if index > max:
                            continue

                    attachment_url = variants[index]['url']

                    response = requests.head(attachment_url)
                    size = int(response.headers['content-length'])

                    if size > (8 * 1024 * 1024):
                        attachment_url = None
                        index += 1

                        if index > max:
                            continue

            else:
                attachment_url = attachment.media_url

            logger.info(f'Downloading {attachment.ext_alt_text} {attachment.type} {attachment_url}')
            attachment_file = requests.get(attachment_url, stream=True)
            attachment_file.raw.decode_content = True
            temp_file = tempfile.NamedTemporaryFile(delete=False)
            temp_file.write(attachment_file.raw.read())
            temp_file.close()

            path = urlparse(attachment_url).path
            file_extension = splitext(path)[1]

            # file_extension = mimetypes.guess_extension(attachment_file.headers['Content-type'])

            # ffs
            if file_extension == '.jpe':
                file_extension = '.jpg'

            upload_file_name = temp_file.name + file_extension
            os.rename(temp_file.name, upload_file_name)

            self.attachments.append((upload_file_name, attachment.ext_alt_text))

            logger.debug(f'Uploading {attachment.ext_alt_text}: {upload_file_name}')

            try:
                self.media_ids.append(self.masto_api.media_post(upload_file_name,
                                                                description=attachment.ext_alt_text))
                os.unlink(upload_file_name)

            except MastodonAPIError as e:
                logger.error(e)
                return False

            except MastodonNetworkError as e:
                logger.error(e)
                return False

        return True

    def send_toot(self, reply_to=None):
        retry_counter = 0
        post_success = False
        spoiler_text = self.settings.tweet_cw_text if self.settings.tweets_behind_cw else ""

        while not post_success and retry_counter < MASTODON_RETRIES:
            logger.info(f'Tooting "{self.clean_content}"')

            if self.media_ids:
                logger.info(f'With media')

            try:
                post = self.masto_api.status_post(
                    self.clean_content,
                    media_ids=self.media_ids,
                    visibility=self.settings.toot_visibility,
                    sensitive=self.sensitive,
                    in_reply_to_id=reply_to,
                    spoiler_text=spoiler_text)

                reply_to = post["id"]
                post_success = True

            except MastodonAPIError as e:
                logger.error(e)

                if retry_counter < MASTODON_RETRIES:
                    retry_counter += 1
                    time.sleep(MASTODON_RETRY_DELAY)

            except MastodonNetworkError as e:
                # assume this is transient
                pass

        if retry_counter == MASTODON_RETRIES:
            logger.error("Retry limit reached.")
            return None

        return reply_to
