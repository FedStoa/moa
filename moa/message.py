class Message:
    class Meta:
        abstract = True

    def __init__(self, settings, data):
        self.message_parts = []
        self.settings = settings
        self.media_ids = []
        self.data = data
        self.type = 'Message'

    def prepare_for_post(self, length=1):
        pass

    @property
    def is_self_reply(self) -> bool:
        return False

    @property
    def should_skip(self) -> bool:
        return False

    @property
    def in_reply_to_id(self):
        return None

    @property
    def media_attachments(self):
        """ Array of { 'url': 'blah', 'description': 'blah'} """
        return []

    def dump_data(self):
        return self.data

    @property
    def url(self):
        return None

    @property
    def clean_content(self):
        return ""
