import html
import logging
import mimetypes
import os
import re
import tempfile

import requests

logger = logging.getLogger('worker')


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

        if self.status.media:

            if not self.__fetched_attachments:
                # we can't get image alt text from the timeline call :/
                fetched_tweet = self.api.GetStatus(
                    status_id=self.status.id,
                    trim_user=True,
                    include_my_retweet=False,
                    include_entities=True,
                    include_ext_alt_text=True
                )

                self.__fetched_attachments = fetched_tweet.media

            return self.__fetched_attachments

        elif self.is_retweet:

            if not self.__fetched_attachments:
                fetched_tweet = self.api.GetStatus(
                    status_id=self.status.retweeted_status.id,
                    trim_user=True,
                    include_my_retweet=False,
                    include_entities=True,
                    include_ext_alt_text=True
                )

                self.__fetched_attachments = fetched_tweet.media

            return self.__fetched_attachments

    @property
    def should_skip(self):

        if self.is_reply and not self.is_self_reply:
            logger.info(f'Skipping reply.')
            return True

        if self.is_retweet and not self.settings.post_rts_to_mastodon:
            logger.info(f'Skipping retweet.')

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
        return self.status.in_reply_to_screen_name is not None

    @property
    def is_self_reply(self):
        return self.status.in_reply_to_user_id == self.status.user.id

    @property
    def urls(self):
        return self.status.urls

    @property
    def sensitive(self):
        return bool(self.status.possibly_sensitive)

    @property
    def clean_content(self):

        quoted_text = None

        if not self.__content:

            if self.is_retweet:
                content = self.status.retweeted_status.full_text

            elif self.is_quoted:

                content = re.sub(r'https?://.*', '', self.status.full_text, flags=re.MULTILINE)
                quoted_text = f"“{self.status.quoted_status.full_text}”"

                for url in self.status.quoted_status.urls:
                    # Unshorten URLs
                    quoted_text = re.sub(url.url, url.expanded_url, quoted_text)

            else:
                content = self.status.full_text

            content = html.unescape(content)
            mentions = re.findall(r'[@]\S*', content)

            if mentions:
                for mention in mentions:
                    # Replace all mentions for an equivalent to clearly signal their origin on Twitter
                    content = re.sub(mention, f"@{mention[1:]}@twitter.com", content)

            for url in self.urls:
                # Unshorten URLs
                content = re.sub(url.url, url.expanded_url, content)

            if self.is_retweet:
                if len(content) > 0:
                    content = f"RT @{self.status.retweeted_status.user.screen_name}@twitter.com\n“{content}”"
                else:
                    content = f"RT @{self.status.retweeted_status.user.screen_name}@twitter.com\n"

            elif self.is_quoted:
                possible_content = f"{content}\n\n{quoted_text}\n{self.url}"

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

        if not self.media:
            return

        for attachment in self.media:
            # l.debug(pp.pformat(attachment.__dict__))

            attachment_url = attachment.media_url

            logger.debug(f'Downloading {attachment.ext_alt_text} {attachment_url}')
            attachment_file = requests.get(attachment_url, stream=True)
            attachment_file.raw.decode_content = True
            temp_file = tempfile.NamedTemporaryFile(delete=False)
            temp_file.write(attachment_file.raw.read())
            temp_file.close()

            file_extension = mimetypes.guess_extension(attachment_file.headers['Content-type'])
            upload_file_name = temp_file.name + file_extension
            os.rename(temp_file.name, upload_file_name)

            self.attachments.append((upload_file_name, attachment.ext_alt_text))

            logger.debug(f'Uploading {attachment.ext_alt_text}: {upload_file_name}')
            self.media_ids.append(self.masto_api.media_post(upload_file_name,
                                                            description=attachment.ext_alt_text))
            os.unlink(upload_file_name)
