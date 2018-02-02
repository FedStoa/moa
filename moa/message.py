class Message:
    class Meta:
        abstract = True

    def __init__(self, settings):
        self.message_parts = []
        self.settings = settings
        self.media_ids = []

    def prepare_for_post(self):
        pass

    @property
    def is_self_reply(self) -> bool:
        return False

    @property
    def in_reply_to_id(self):
        return None

    @property
    def media_attachments(self):
        """ Array of { 'url': 'blah', 'description': 'blah'} """
        return []
