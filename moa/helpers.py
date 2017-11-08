import logging
import time
from twitter import TwitterError

TWITTER_RETRIES = 3
TWITTER_RETRY_DELAY = 20

logger = logging.getLogger('worker')


def send_tweet(tweet, reply_to, media_ids, twitter_api):

    retry_counter = 0
    post_success = False

    while not post_success and retry_counter < TWITTER_RETRIES:

        logger.info(f'Tweeting "{tweet}"')

        if media_ids:
            logger.info(f'With media {media_ids}')

        try:
            reply_to = twitter_api.PostUpdate(tweet,
                                              media=media_ids,
                                              in_reply_to_status_id=reply_to).id
        except TwitterError as e:
            logger.error(e.message)

            if e.message[0]['code'] == 187:
                # Status is a duplicate
                return
            if retry_counter < TWITTER_RETRIES:
                retry_counter += 1
                time.sleep(TWITTER_RETRY_DELAY)

        post_success = True

    if retry_counter == TWITTER_RETRIES:
        logger.error("Retry limit reached.")
        return None

    return reply_to
