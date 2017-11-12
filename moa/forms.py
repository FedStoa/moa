from flask_wtf import FlaskForm
from wtforms import BooleanField, StringField, SelectField, RadioField
from wtforms.validators import DataRequired, Email


class SettingsForm(FlaskForm):
    enabled = BooleanField('Enabled?')

    post_to_twitter = BooleanField('Post Public toots to Twitter?')
    post_private_to_twitter = BooleanField('Post Private toots to Twitter?')
    post_boosts_to_twitter = BooleanField('Post Boosts to Twitter?')
    split_twitter_messages = BooleanField('Split long toots on Twitter?')
    post_rts_to_mastodon = BooleanField('Post RTs to Mastodon?')

    post_to_mastodon = BooleanField('Post to Mastodon?')
    toot_visibility = RadioField('Toot visibility', choices=[
        ('public', 'Public'),
        ('private', "Private"),
        ('unlisted', 'Unlisted'),
    ])


class MastodonIDForm(FlaskForm):
    mastodon_id = StringField('Enter your Mastodon ID', validators=[DataRequired(), Email()])
