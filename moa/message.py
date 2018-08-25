from typing import Any, List

from moa.models import TSettings


class Message:
    class Meta:
        abstract = True

    def __init__(self, settings: TSettings, data: Any) -> None:
        self.message_parts: List[str] = []
        self.settings = settings
        self.data = data
        self.type = 'Message'
        self.cw = None

    def prepare_for_post(self, length=1):
        raise Exception("Needs Implementation")

    @property
    def id(self) -> int:
        raise Exception("Needs Implementation")

    @property
    def is_self_reply(self) -> bool:
        raise Exception("Needs Implementation")

    @property
    def should_skip(self) -> bool:
        raise Exception("Needs Implementation")

    @property
    def in_reply_to_id(self):
        raise Exception("Needs Implementation")

    @property
    def media_attachments(self):
        """ Array of { 'url': 'blah', 'description': 'blah'} """
        raise Exception("Needs Implementation")

    def dump_data(self):
        raise Exception("Needs Implementation")

    @property
    def url(self):
        raise Exception("Needs Implementation")

    @property
    def clean_content(self):
        raise Exception("Needs Implementation")

    @property
    def is_sensitive(self):
        raise Exception("Needs Implementation")
