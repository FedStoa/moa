import logging

from instagram.helper import datetime_to_timestamp

from moa.message import Message

logger = logging.getLogger('worker')


class Insta(Message):

    def __init__(self, settings, data):
        super().__init__(settings, data)

        self.type = 'Insta'

    @property
    def id(self):
        ts = datetime_to_timestamp(self.data.created_time)

        return ts

    @property
    def url(self):
        return self.data.link

    @property
    def clean_content(self):
        if self.data.caption:
            return self.data.caption.text
        else:
            return ""

    @property
    def media_attachments(self):
        """ Array of { 'url': 'blah', 'description': 'blah'} """
        return [{"url": self.data.images['standard_resolution'].url}]

    def dump_data(self):
        return self.data.__dict__

    @property
    def should_skip(self) -> bool:
        return False

    @property
    def is_self_reply(self) -> bool:
        return False

    @property
    def sensitive(self) -> bool:
        return False

    def prepare_for_post(self, length=1):
        suffix = f"\n{self.url}"

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


