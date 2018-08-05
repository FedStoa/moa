from flask_wtf import FlaskForm
from wtforms import BooleanField, RadioField, StringField
from wtforms.validators import DataRequired, Email, Length


class SettingsForm(FlaskForm):
    enabled = BooleanField('Bridging Enabled?')

    post_to_twitter = BooleanField('Post Public toots to Twitter?')
    post_private_to_twitter = BooleanField('Post Private toots to Twitter?')
    post_unlisted_to_twitter = BooleanField('Post Unlisted toots to Twitter?')
    post_boosts_to_twitter = BooleanField('Post Boosts to Twitter?')
    split_twitter_messages = BooleanField('Split long toots on Twitter?')

    post_rts_to_mastodon = BooleanField('Post RTs to Mastodon?')
    post_quotes_to_mastodon = BooleanField('Post quoted tweets to Mastodon?')
    post_to_mastodon = BooleanField('Post tweets to Mastodon?')
    toot_visibility = RadioField('Toot visibility', choices=[
        ('public', 'Public'),
        ('private', "Private"),
        ('unlisted', 'Unlisted'),
    ])
    tweets_behind_cw = BooleanField('Always Post Tweets behind a Content Warning?')
    tweet_cw_text = StringField('',
                                validators=[Length(min=1, message="Content Warning text can't be empty")])

    instagram_enabled = BooleanField('Import posts from Instagram?')
    instagram_post_to_twitter = BooleanField('Post Instagrams to Twitter?')
    instagram_post_to_mastodon = BooleanField('Post Instagrams to Mastodon?')


class MastodonIDForm(FlaskForm):
    mastodon_id = StringField('Enter your Mastodon ID', validators=[DataRequired(), Email()])
