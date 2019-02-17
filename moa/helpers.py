import re

import twitter
from flask import render_template
from flask_mail import Message, Mail
from twitter import TwitterError


def blacklisted(name, bl):
    for p in bl:
        if re.match(p, name):
            return True

    return False


def email_bridge_details(app, bridge):
    if app.config.get('MAIL_SERVER', None):
        mail = Mail(app)

        twitter_follower_count = 0

        if bridge.twitter_oauth_token:
            # Fetch twitter follower count
            twitter_api = twitter.Api(
                    consumer_key=app.config['TWITTER_CONSUMER_KEY'],
                    consumer_secret=app.config['TWITTER_CONSUMER_SECRET'],
                    access_token_key=bridge.twitter_oauth_token,
                    access_token_secret=bridge.twitter_oauth_secret
            )
            try:
                follower_list = twitter_api.GetFollowerIDs()

            except TwitterError as e:
                twitter_follower_count = e

            else:
                twitter_follower_count = len(follower_list)

        body = render_template('new_user_email.txt.j2',
                               bridge=bridge,
                               twitter_follower_count=twitter_follower_count)

        msg = Message(subject="moa.party bridge updated",
                      body=body,
                      recipients=[app.config.get('MAIL_TO', None)])

        try:
            mail.send(msg)

        except Exception as e:
            app.logger.error(e)


def send_blacklisted_email(app, username):
    if app.config.get('MAIL_SERVER', None):
        mail = Mail(app)
        body = render_template('access_denied.txt.j2', user=f"https://twitter.com/{username}")
        msg = Message(subject="moa access denied",
                      body=body,
                      recipients=[app.config.get('MAIL_TO', None)])

        try:
            mail.send(msg)

        except Exception as e:
            app.logger.error(e)


BASE62 = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
# Taken from https://stackoverflow.com/questions/1119722/base-62-conversion


def b62_encode(num, alphabet=BASE62):
    """Encode a positive number in Base X

    Arguments:
    - `num`: The number to encode
    - `alphabet`: The alphabet to use for encoding
    """
    if num == 0:
        return alphabet[0]
    arr = []
    base = len(alphabet)
    while num:
        num, rem = divmod(num, base)
        arr.append(alphabet[rem])
    arr.reverse()
    return ''.join(arr)


def b62_decode(string, alphabet=BASE62):
    """Decode a Base X encoded string into the number

    Arguments:
    - `string`: The encoded string
    - `alphabet`: The alphabet to use for encoding
    """
    base = len(alphabet)
    strlen = len(string)
    num = 0

    idx = 0
    for char in string:
        power = (strlen - (idx + 1))
        num += alphabet.index(char) * (base ** power)
        idx += 1

    return num
