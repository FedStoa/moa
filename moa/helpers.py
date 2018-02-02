import logging
import time

from twitter import TwitterError

TWITTER_RETRIES = 3
TWITTER_RETRY_DELAY = 5

logger = logging.getLogger('worker')


