from datetime import datetime
from sqlalchemy import MetaData, Column, Integer, String, DateTime, BigInteger, ForeignKey, Boolean, PickleType, Float, \
    event
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship

metadata = MetaData()
Base = declarative_base(metadata=metadata)


class MastodonHost(Base):

    __tablename__ = 'mastodon_host'

    id = Column(Integer, primary_key=True)
    hostname = Column(String(80), nullable=False)
    client_id = Column(String(64), nullable=False)
    client_secret = Column(String(64), nullable=False)
    created = Column(DateTime, default=datetime.utcnow)
    bridges = relationship('Bridge', backref='mastodon_host', lazy='dynamic')


class Bridge(Base):

    __tablename__ = 'bridge'

    id = Column(Integer, primary_key=True)
    twitter_oauth_token = Column(String(80), nullable=False)
    twitter_oauth_secret = Column(String(80), nullable=False)
    twitter_last_id = Column(BigInteger, default=0)
    twitter_handle = Column(String(15), nullable=False)

    mastodon_access_code = Column(String(80), nullable=False)
    mastodon_last_id = Column(BigInteger, default=0)
    mastodon_account_id = Column(BigInteger, default=0)
    mastodon_user = Column(String(30), nullable=False)
    mastodon_host_id = Column(Integer, ForeignKey('mastodon_host.id'), nullable=False)

    enabled = Column(Boolean, nullable=False, default=False)

    settings = Column(PickleType)

    created = Column(DateTime, default=datetime.utcnow)
    updated = Column(DateTime)

    def __repr__(self):
        return f"Twitter: {self.twitter_handle}  Mastodon: {self.mastodon_user}"


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

    time = Column(Float, default=0.0)
    avg = Column(Float, default=0.0)

    worker = Column(Integer, nullable=False)

    def __init__(self, worker=1):

        self.tweets = 0
        self.toots = 0
        self.worker = worker

    @property
    def formatted_time(self):

        m, s = divmod(self.time, 60)
        return f"{m:02.0f}:{s:02.0f}"

    @property
    def items(self):
        return self.tweets + self.toots

    def add_toot(self, toot):
        self.toots += 1

    def add_tweet(self, tweet):
        self.tweets += 1


@event.listens_for(WorkerStat.time, 'set')
def receive_time_set(target, value, oldvalue, initiator):
    if target.items > 0:
        target.avg = value / target.items
    else:
        target.avg = 0


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

        self.post_to_twitter = True
        self.post_private_to_twitter = False
        post_unlisted_to_twitter = False
        self.split_twitter_messages = True
        self.post_boosts_to_twitter = True

        self.post_to_mastodon = True
        self.post_rts_to_mastodon = True
        self.toot_visibility = 'public'


if __name__ == '__main__':

    import os
    import importlib
    from sqlalchemy import create_engine

    moa_config = os.environ.get('MOA_CONFIG', 'DevelopmentConfig')
    config = getattr(importlib.import_module('config'), moa_config)

    if "mysql" in config.SQLALCHEMY_DATABASE_URI:
        import pymysql

    engine = create_engine(config.SQLALCHEMY_DATABASE_URI, echo=True)
    metadata = MetaData(engine, reflect=True)
    print("Creating Tables")

    Base.metadata.create_all(engine)
    # metadata.create_all()
    for t in metadata.tables:
        # t.create()
        print("Table: ", t)
