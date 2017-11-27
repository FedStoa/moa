class Settings:
    # These are defined in 2 places because the unpickled settings may be missing a property that's been added

    post_to_twitter = True
    post_private_to_twitter = False
    post_unlisted_to_twitter = False
    split_twitter_messages = True
    post_boosts_to_twitter = True

    post_to_mastodon = True
    post_rts_to_mastodon = True
    toot_visibility = 'public'

    def __init__(self):
        self.post_to_twitter = True  # This means post public toots
        self.post_private_to_twitter = False
        self.post_unlisted_to_twitter = False
        self.split_twitter_messages = True
        self.post_boosts_to_twitter = True

        self.post_to_mastodon = True # This means post non-RT tweets
        self.post_rts_to_mastodon = True
        self.toot_visibility = 'public'

    @property
    def post_to_twitter_enabled(self):
        return self.post_to_twitter or \
               self.post_private_to_twitter or \
               self.post_unlisted_to_twitter or \
               self.post_boosts_to_twitter

    @property
    def post_to_mastodon_enabled(self):
        return self.post_to_mastodon or \
               self.post_rts_to_mastodon


if __name__ == '__main__':
    import os
    import sys
    import importlib
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from pprint import pprint as pp

    from .models import Bridge

    moa_config = os.environ.get('MOA_CONFIG', 'DevelopmentConfig')
    config = getattr(importlib.import_module('config'), moa_config)

    engine = create_engine(config.SQLALCHEMY_DATABASE_URI)
    engine.connect()
    session = Session(engine)

    bridge_id = int(sys.argv[1])

    bridge = session.query(Bridge).filter_by(id=bridge_id).first()

    pp(bridge.settings.__dict__)
