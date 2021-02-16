from flask_wtf import FlaskForm
from wtforms import BooleanField, RadioField, StringField
from wtforms.validators import DataRequired, Email, Length

from moa.models import CON_XP_DISABLED, CON_XP_ONLYIF, CON_XP_UNLESS


class SettingsForm(FlaskForm):
    enabled = BooleanField('Crossposting Enabled?')
    conditional_posting = RadioField('Conditional crossposting', choices=[
        (CON_XP_DISABLED, 'Disabled'),
        (CON_XP_ONLYIF, "Crosspost only if hashtag #moa or #xp is present"),
        (CON_XP_UNLESS, 'Crosspost unless hashtag #nomoa or #noxp is present'),
    ])

    post_to_twitter = BooleanField('Post Public toots to Twitter?')
    post_private_to_twitter = BooleanField('Post Private toots to Twitter?')
    post_unlisted_to_twitter = BooleanField('Post Unlisted toots to Twitter?')
    post_boosts_to_twitter = BooleanField('Post Boosts to Twitter?')
    split_twitter_messages = BooleanField('Split long toots on Twitter?')
    post_sensitive_behind_link = BooleanField('Link toot with warning if there are sensitive images?')
    sensitive_link_text = StringField('', validators=[Length(min=1, message="Warning can't be empty")])
    remove_cw = BooleanField("Remove toot content warning?")

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
    instagram_include_link = BooleanField('Include link to instagram post')

    post_to_gitlab = BooleanField('Post Public posts to Gitlab?')
    # TODO add validator when I figure out how to do it conditionally
    gitlab_project = StringField('')

    def remove_masto_and_twitter_fields(self):
        del self.post_to_twitter
        del self.post_private_to_twitter
        del self.post_unlisted_to_twitter
        del self.post_boosts_to_twitter
        del self.split_twitter_messages
        del self.post_sensitive_behind_link
        del self.sensitive_link_text
        del self.remove_cw

        del self.post_rts_to_mastodon
        del self.post_quotes_to_mastodon
        del self.post_to_mastodon
        del self.toot_visibility

        del self.tweets_behind_cw
        del self.tweet_cw_text


class MastodonIDForm(FlaskForm):
    mastodon_id = StringField('Enter your Mastodon ID', validators=[DataRequired()])
