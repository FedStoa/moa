import logging
import time

from mastodon.Mastodon import MastodonAPIError
from twitter import TwitterError

TWITTER_RETRIES = 3
TWITTER_RETRY_DELAY = 20
MASTODON_RETRIES = 3
MASTODON_RETRY_DELAY = 20

logger = logging.getLogger('worker')


def send_tweet(tweet, reply_to, media_ids, twitter_api):
    retry_counter = 0
    post_success = False

    while not post_success and retry_counter < TWITTER_RETRIES:

        logger.info(f'Tweeting "{tweet}"')

        if media_ids:
            logger.info(f'With media')

        try:
            reply_to = twitter_api.PostUpdate(tweet,
                                              media=media_ids,
                                              in_reply_to_status_id=reply_to,
                                              verify_status_length=False).id
            post_success = True

        except TwitterError as e:
            logger.error(e.message)

            if e.message[0]['code'] == 187:
                # Status is a duplicate
                return None
            if retry_counter < TWITTER_RETRIES:
                retry_counter += 1
                time.sleep(TWITTER_RETRY_DELAY)

    if retry_counter == TWITTER_RETRIES:
        logger.error("Retry limit reached.")
        return None

    return reply_to


def send_toot(tweet, settings, mast_api, reply_to=None):
    retry_counter = 0
    post_success = False

    while not post_success and retry_counter < MASTODON_RETRIES:
        logger.info(f'Tooting "{tweet.clean_content}"')

        if tweet.media_ids:
            logger.info(f'With media')

        try:
            post = mast_api.status_post(
                tweet.clean_content,
                media_ids=tweet.media_ids,
                visibility=settings.toot_visibility,
                sensitive=tweet.sensitive,
                in_reply_to_id=reply_to)

            reply_to = post["id"]
            post_success = True

        except MastodonAPIError as e:
            logger.error(e)

            if retry_counter < MASTODON_RETRIES:
                retry_counter += 1
                time.sleep(MASTODON_RETRY_DELAY)

    if retry_counter == MASTODON_RETRIES:
        logger.error("Retry limit reached.")
        return None

    return reply_to
