from datetime import datetime, timedelta
from sqlalchemy import MetaData, Column, Integer, String, DateTime, BigInteger, ForeignKey, Boolean, PickleType, Float, \
    event
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship

metadata = MetaData()
Base = declarative_base(metadata=metadata)

DEFER_TIME = 60 * 15
DEFER_STRIKES = 86400 / DEFER_TIME
DEFER_OK = 0
DEFER_REPEAT = 1
DEFER_FAILED = 2


class MastodonHost(Base):
    __tablename__ = 'mastodon_host'

    id = Column(Integer, primary_key=True)
    hostname = Column(String(80), nullable=False)
    client_id = Column(String(64), nullable=False)
    client_secret = Column(String(64), nullable=False)
    created = Column(DateTime, default=datetime.utcnow)
    bridges = relationship('Bridge', backref='mastodon_host', lazy='dynamic')
    defer_until = Column(DateTime)
    defer_count = Column(Integer)

    def defer(self):
        self.defer_until = datetime.now() + timedelta(seconds=DEFER_TIME)

        if not self.defer_count:
            self.defer_count = 1
            return DEFER_OK
        else:
            self.defer_count += 1

            if self.defer_count >= DEFER_STRIKES:
                return DEFER_FAILED
            else:
                return DEFER_REPEAT

    def defer_reset(self):
        self.defer_count = 0


CON_XP_DISABLED = 'disabled'
CON_XP_ONLYIF = 'onlyif'
CON_XP_ONLYIF_TAGS = ['moa', 'xp']

CON_XP_UNLESS = 'unless'
CON_XP_UNLESS_TAGS = ['nomoa', 'noxp']

class TSettings(Base):
    __tablename__ = 'settings'
    __table_args__ = {'mysql_charset': 'utf8mb4', 'mysql_collate': 'utf8mb4_general_ci'}

    id = Column(Integer, primary_key=True)
    bridge = relationship('Bridge', backref='t_settings', lazy='dynamic')
    conditional_posting = Column(String(10), nullable=False, server_default=CON_XP_DISABLED, default=CON_XP_DISABLED)

    # Masto -> Twitter
    post_to_twitter = Column(Boolean, nullable=False, default=True)  # This means post public toots
    post_private_to_twitter = Column(Boolean, nullable=False, default=False)
    post_unlisted_to_twitter = Column(Boolean, nullable=False, default=False)
    split_twitter_messages = Column(Boolean, nullable=False, default=True)
    post_boosts_to_twitter = Column(Boolean, nullable=False, default=True)
    post_sensitive_behind_link = Column(Boolean, nullable=False, default=False)
    sensitive_link_text = Column(String(100), nullable=False, default='(NSFW Image)')

    # Twitter -> Masto
    post_to_mastodon = Column(Boolean, nullable=False, default=True)
    post_rts_to_mastodon = Column(Boolean, nullable=False, default=True)
    post_quotes_to_mastodon = Column(Boolean, nullable=False, default=True)
    toot_visibility = Column(String(40), nullable=False, default='public')
    tweets_behind_cw = Column(Boolean, nullable=False, default=False)
    tweet_cw_text = Column(String(100), nullable=False, default="From birdsite")

    instagram_post_to_twitter = Column(Boolean, nullable=False, default=False)
    instagram_post_to_mastodon = Column(Boolean, nullable=False, default=False)
    instagram_include_link = Column(Boolean, nullable=False, default=True)

    def __init__(self, **kwargs):
        kwargs.setdefault('post_to_twitter', True)
        kwargs.setdefault('post_private_to_twitter', False)
        kwargs.setdefault('post_unlisted_to_twitter', False)
        kwargs.setdefault('split_twitter_messages', True)
        kwargs.setdefault('post_boosts_to_twitter', True)
        kwargs.setdefault('post_sensitive_behind_link', False)
        kwargs.setdefault('sensitive_link_text', '(NSFW Image)')

        kwargs.setdefault('post_to_mastodon', True)
        kwargs.setdefault('post_rts_to_mastodon', True)
        kwargs.setdefault('post_quotes_to_mastodon', True)
        kwargs.setdefault('toot_visibility', 'public')
        kwargs.setdefault('tweets_behind_cw', False)
        kwargs.setdefault('tweet_cw_text', "From birdsite")

        kwargs.setdefault('instagram_post_to_twitter', False)
        kwargs.setdefault('instagram_post_to_mastodon', False)
        kwargs.setdefault('instagram_include_link', True)

        super(TSettings, self).__init__(**kwargs)

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


class Bridge(Base):
    __tablename__ = 'bridge'

    id = Column(Integer, primary_key=True)
    twitter_oauth_token = Column(String(80))
    twitter_oauth_secret = Column(String(80))
    twitter_last_id = Column(BigInteger, default=0)
    twitter_handle = Column(String(15))

    mastodon_access_code = Column(String(80))
    mastodon_last_id = Column(BigInteger, default=0)
    mastodon_account_id = Column(BigInteger, default=0)
    mastodon_user = Column(String(30))
    mastodon_host_id = Column(Integer, ForeignKey('mastodon_host.id'))

    enabled = Column(Boolean, nullable=False, default=False)

    instagram_access_code = Column(String(80))
    instagram_last_id = Column(BigInteger, default=0)
    instagram_account_id = Column(BigInteger, default=0)
    instagram_handle = Column(String(30))

    t_settings_id = Column(Integer, ForeignKey('settings.id'), nullable=True)
    metadata_id = Column(Integer, ForeignKey('bridgemetadata.id'), nullable=True)

    worker_id = Column(Integer, default=1)

    created = Column(DateTime, default=datetime.utcnow)
    updated = Column(DateTime)

    def __repr__(self):
        return f"{self.id}: Twitter: {self.twitter_handle}  Mastodon: {self.mastodon_user}"


class Mapping(Base):
    __tablename__ = 'mapping'
    id = Column(Integer, primary_key=True)
    mastodon_id = Column(BigInteger, default=0)
    twitter_id = Column(BigInteger, default=0)
    created = Column(DateTime, default=datetime.utcnow)


class WorkerStat(Base):
    __tablename__ = 'workerstat'
    id = Column(Integer, primary_key=True)
    created = Column(DateTime, default=datetime.utcnow)

    tweets = Column(Integer, default=0)
    toots = Column(Integer, default=0)
    instas = Column(Integer, default=0)

    time = Column(Float, default=0.0)
    avg = Column(Float, default=0.0)

    worker = Column(Integer, nullable=False)

    def __init__(self, worker=1):
        self.tweets = 0
        self.toots = 0
        self.instas = 0
        self.worker = worker

    @property
    def formatted_time(self):
        m, s = divmod(self.time, 60)
        return f"{m:02.0f}:{s:02.0f}"

    @property
    def items(self):
        return self.tweets + self.toots + self.instas

    def add_toot(self):
        self.toots += 1

    def add_tweet(self):
        self.tweets += 1

    def add_insta(self):
        self.instas += 1


class BridgeStat(Base):
    __tablename__ = 'bridgestat'
    id = Column(Integer, primary_key=True)
    created = Column(DateTime, default=datetime.utcnow)
    bridge_id = Column(Integer, ForeignKey('bridge.id'), nullable=True)

    tweets = Column(Integer, default=0, server_default="0")
    toots = Column(Integer, default=0, server_default="0")
    instas = Column(Integer, default=0, server_default="0")

    def __init__(self, bridge_id):
        self.bridge_id = bridge_id

    @property
    def items(self):
        return self.tweets + self.toots + self.instas

    def add_toot(self):
        self.toots += 1

    def add_tweet(self):
        self.tweets += 1

    def add_insta(self):
        self.instas += 1


class BridgeMetadata(Base):
    __tablename__ = 'bridgemetadata'
    id = Column(Integer, primary_key=True)
    created = Column(DateTime, default=datetime.utcnow)

    bridge = relationship('Bridge', backref='md', lazy='dynamic')
    last_tweet = Column(DateTime, default=datetime.utcnow)
    last_toot = Column(DateTime, default=datetime.utcnow)
    is_bot = Column(Boolean, default=0, server_default="0")
    worker_id = Column(Integer, default=1)


@event.listens_for(WorkerStat.time, 'set')
def receive_time_set(target, value, oldvalue, initiator):
    if target.items > 0:
        target.avg = value / target.items
    else:
        target.avg = 0


if __name__ == '__main__':

    import os
    import importlib
    from sqlalchemy import create_engine

    moa_config = os.environ.get('MOA_CONFIG', 'DevelopmentConfig')
    config = getattr(importlib.import_module('config'), moa_config)

    if "mysql" in config.SQLALCHEMY_DATABASE_URI:
        import pymysql

    engine = create_engine(config.SQLALCHEMY_DATABASE_URI)
    metadata = MetaData(engine, reflect=True)
    print("Creating Tables")

    Base.metadata.create_all(engine)
    # metadata.create_all()
    for t in metadata.tables:
        # t.create()
        print("Table: ", t)

    print("./tools/flask_db.sh stamp head to finish")
