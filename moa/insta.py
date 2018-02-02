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
        return self.data.caption.text

    @property
    def media_attachments(self):
        """ Array of { 'url': 'blah', 'description': 'blah'} """
        return [{"url": self.data.images['standard_resolution'].url}]

    def dump_data(self):
        return self.data.__dict__

    def prepare_for_post(self, length=1):
        suffix = f"\n{self.url}"
        leftover_length = length - len(suffix)
        truncated_text = self.clean_content[:leftover_length] + suffix

        # logger.debug(f"Truncated Text length is {len(truncated_text)}")
        # logger.debug(truncated_text)

        self.message_parts.append(truncated_text)


