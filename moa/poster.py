
class Poster:

    def __init__(self, send, session):
        self.send = send
        self.session = session
        self.media_ids = []

    def reset(self) -> None:
        self.media_ids = []
