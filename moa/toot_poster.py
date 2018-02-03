from os.path import splitext
from urllib.parse import urlparse

import os
from mastodon.Mastodon import MastodonAPIError, MastodonNetworkError

from message import Message
from poster import Poster
import logging
import requests
import tempfile

logger = logging.getLogger('worker')

MASTODON_RETRIES = 3
MASTODON_RETRY_DELAY = 5


class TootPoster(Poster):

    def __init__(self, send, session, api, bridge):
        super().__init__(send, session)

        self.api = api
        self.bridge = bridge

    def post(self, post: Message) -> bool:
        pass

    def send_toot(self, status_text, reply_to, media_ids):
        retry_counter = 0
        post_success = False
        spoiler_text = self.settings.tweet_cw_text if self.settings.tweets_behind_cw else ""

        while not post_success and retry_counter < MASTODON_RETRIES:
            logger.info(f'Tooting "{self.clean_content}"')

            if self.media_ids:
                logger.info(f'With media')

            try:
                post = self.masto_api.status_post(
                    self.clean_content,
                    media_ids=self.media_ids,
                    visibility=self.settings.toot_visibility,
                    sensitive=self.sensitive,
                    in_reply_to_id=reply_to,
                    spoiler_text=spoiler_text)

                reply_to = post["id"]
                post_success = True

            except MastodonAPIError as e:
                logger.error(e)

                if retry_counter < MASTODON_RETRIES:
                    retry_counter += 1
                    time.sleep(MASTODON_RETRY_DELAY)

            except MastodonNetworkError as e:
                # assume this is transient
                pass

        if retry_counter == MASTODON_RETRIES:
            logger.error("Retry limit reached.")
            return None

        return reply_to


    def transfer_attachments(self, post: Message):

        for attachment in post.media_attachments:

            logger.info(f'Downloading {attachment.description}  {attachment.url}')
            attachment_file = requests.get(attachment.url, stream=True)
            attachment_file.raw.decode_content = True
            temp_file = tempfile.NamedTemporaryFile(delete=False)
            temp_file.write(attachment_file.raw.read())
            temp_file.close()

            path = urlparse(attachment.url).path
            file_extension = splitext(path)[1]

            # file_extension = mimetypes.guess_extension(attachment_file.headers['Content-type'])

            # ffs
            if file_extension == '.jpe':
                file_extension = '.jpg'

            upload_file_name = temp_file.name + file_extension
            os.rename(temp_file.name, upload_file_name)

            # self.attachments.append((upload_file_name, attachment.ext_alt_text))

            logger.debug(f'Uploading {attachment.description}: {upload_file_name}')

            try:
                post.media_ids.append(self.api.media_post(upload_file_name,description=attachment.description))
                os.unlink(upload_file_name)

            except MastodonAPIError as e:
                logger.error(e)
                return False

            except MastodonNetworkError as e:
                logger.error(e)
                return False

        return True

