import logging

import re
from datetime import datetime, timezone

from instagram.helper import datetime_to_timestamp

from moa.message import Message
from moa.tweet import HOUR_CUTOFF

logger = logging.getLogger('worker')


class Insta(Message):

    def __init__(self, settings, data):
        super().__init__(settings, data)

        self.type = 'Insta'
        self.__content = None

    @property
    def id(self):
        ts = datetime_to_timestamp(self.data.created_time)

        return ts

    @property
    def url(self):
        return self.data.link

    @property
    def too_old(self) -> bool:
        now = datetime.now(timezone.utc)
        td = now - self.data.created_time
        return td.total_seconds() >= 60 * 60 * HOUR_CUTOFF

    @property
    def clean_content(self):

        if not self.__content:

            if self.data.caption:
                self.__content = self.data.caption.text
            else:
                self.__content = ""

            mentions = re.findall(r'@[a-zA-Z0-9_]{1,30}', self.__content)

            for mention in mentions:
                # Replace all mentions for an equivalent to clearly signal their origin on Twitter
                self.__content = re.sub(mention, f"{mention}@instagram.com", self.__content)

        return self.__content

    @property
    def media_attachments(self):
        """ Array of { 'url': 'blah', 'description': 'blah'} """

        if self.data.type == "image":
            return [{"url": self.data.images['standard_resolution'].url}]

        elif self.data.type == 'carousel':
            attachments = []
            for i in self.data.carousel_media:
                img = i.get('standard_resolution', None)
                if img:
                    attachments.append({'url': img.url})
            # attachments = [{"url": i['standard_resolution'].url} for i in self.data.carousel_media]
            if len(attachments) > 4:
                attachments = attachments[:4]
            return attachments

        else:
            return [{"url": self.data.videos['standard_resolution'].url}]

    def dump_data(self):
        return self.data.__dict__

    @property
    def should_skip(self) -> bool:

        if self.too_old:
            logger.info(f'Skipping because >= {HOUR_CUTOFF} hours old.')
            return True

        return False

    @property
    def should_skip_mastodon(self) -> bool:

        if not self.settings.instagram_post_to_mastodon:
            return True

        elif self.settings.conditional_posting:
            for ht in self.data.tags:
                if ht.name == 'nm':
                    logger.info(f'Skipping because #nm found')
                    return True

        return False

    @property
    def should_skip_twitter(self) -> bool:

        if not self.settings.instagram_post_to_twitter:
            return True

        elif self.settings.conditional_posting:
            for ht in self.data.tags:
                if ht.name == 'nt':
                    logger.info(f'Skipping because #nt found')
                    return True

        return False

    @property
    def is_self_reply(self) -> bool:
        return False

    @property
    def is_sensitive(self) -> bool:
        return False

    def prepare_for_post(self, length=1):

        if self.settings.instagram_include_link:
            suffix = f"\n{self.url}"
        else:
            suffix = ""

        content = self.clean_content

        if len(content + suffix) > length:
            suffix = "…" + suffix
            logger.debug(f"Truncating text")

            trunc_length = length - len(suffix)
            content = self.clean_content[:trunc_length] + suffix

        else:

            content = content + suffix

        logger.debug(f"Truncated Text length is {len(content)}")
        # logger.debug(truncated_text)

        self.message_parts = [content]


