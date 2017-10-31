from flask_sqlalchemy import SQLAlchemy
from datetime import datetime


db = SQLAlchemy()

class MastodonHost(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    hostname = db.Column(db.String(80), nullable=False)
    client_id = db.Column(db.String(64), nullable=False)
    client_secret = db.Column(db.String(64), nullable=False)
    created = db.Column(db.DateTime, default=datetime.utcnow)


class Bridge(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    twitter_oauth_token = db.Column(db.String(80), nullable=False)
    twitter_oauth_secret = db.Column(db.String(80), nullable=False)
    twitter_last_id = db.Column(db.BigInteger)
    twitter_handle = db.Column(db.String(15), nullable=False)

    mastodon_access_token = db.Column(db.String(80), nullable=False)
    mastodon_last_id = db.Column(db.BigInteger)
    mastodon_user = db.Column(db.String(30), nullable=False)
    mastodon_host_id = db.Column(db.Integer, db.ForeignKey('mastodon_host.id'), nullable=False)

    enabled = db.Column(db.Boolean, nullable=False, default=False)

    settings = db.Column(db.PickleType)

    created = db.Column(db.DateTime, default=datetime.utcnow)
    updated = db.Column(db.DateTime)

    def __repr__(self):
        return '<User %r>' % self.username
