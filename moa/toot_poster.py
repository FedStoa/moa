import logging
import os
import sys
import tempfile
import time
from os.path import splitext
from typing import Optional
from urllib.parse import urlparse
import pprint as pp

import requests
from mastodon.Mastodon import MastodonAPIError, MastodonNetworkError, MastodonRatelimitError, MastodonUnauthorizedError
from pymysql import OperationalError
from requests.exceptions import SSLError
from urllib3.exceptions import ProtocolError, ConnectionError

from moa.helpers import MoaMediaUploadException
from moa.message import Message
from moa.models import Mapping
from moa.poster import Poster

logger = logging.getLogger('worker')

MASTODON_RETRIES = 1
MASTODON_RETRY_DELAY = 5
MASTODON_TOOT_LENGTH = 495


class TootPoster(Poster):

    def __init__(self, send, session, api, bridge):
        super().__init__(send, session)

        self.api = api
        self.bridge = bridge

    def post(self, post: Message) -> bool:

        self.reset()

        if post.should_skip:
            return False

        logger.info(f"TootPoster Working on {post.type} {post.id}")
        # logger.debug(post.dump_data())

        post.prepare_for_post(length=MASTODON_TOOT_LENGTH)

        if self.send:

            self.transfer_attachments(post)

            reply_to = None
            visibility = self.bridge.t_settings.toot_visibility
            if post.is_retweet:
                visibility = 'unlisted'

            if post.is_self_reply:
                mapping = self.session.query(Mapping).filter_by(twitter_id=post.in_reply_to_id).first()

                if mapping:
                    reply_to = mapping.mastodon_id
                    logger.info(f"Replying to mastodon status {reply_to}")
                else:
                    # we don't know about this message which means it wasn't posted so let's skip it
                    logger.info("Skipping reply to unknown message")
                    return False

            if self.send:
                mastodon_last_id = self.send_toot(post.message_parts[0],
                                                  reply_to,
                                                  media_ids=self.media_ids,
                                                  sensitive=post.is_sensitive,
                                                  msg_type=post.type,
                                                  cw=post.cw,
                                                  visibility=visibility)

                if mastodon_last_id:
                    m = Mapping()
                    m.mastodon_id = mastodon_last_id
                    m.twitter_id = post.id
                    self.session.add(m)

                    self.bridge.mastodon_last_id = mastodon_last_id

                try:
                    self.session.commit()
                except OperationalError as e:
                    # MySQL might be down
                    logger.error(e)
                    sys.exit()

        else:
            logger.info(post.media_attachments)
            logger.info(post.clean_content)
            return False

        return True

    def send_toot(self, status_text: str, reply_to: int, media_ids=None, sensitive=False, msg_type="", cw=None, visibility='public') -> Optional[int]:
        retry_counter = 0
        post_success = False
        spoiler_text = ""

        if msg_type == 'Tweet':
            if self.bridge.t_settings.tweets_behind_cw:
                spoiler_text = self.bridge.t_settings.tweet_cw_text

            if cw:
                spoiler_text = cw

        while not post_success and retry_counter < MASTODON_RETRIES:
            logger.info(f'Tooting "{status_text}"')

            if media_ids:
                logger.info(f'With media')

            try:
                post = self.api.status_post(
                        status_text,
                        media_ids=media_ids,
                        visibility=visibility,
                        sensitive=sensitive,
                        in_reply_to_id=reply_to,
                        spoiler_text=spoiler_text)

                reply_to = post["id"]
                post_success = True
                logger.info(f"Toot ID: {reply_to}")

            except MastodonAPIError as e:
                logger.error(e)

                if 'Forbidden' in repr(e):
                    self.bridge.enabled = False
                    return None

                if retry_counter < MASTODON_RETRIES:
                    retry_counter += 1
                    # time.sleep(MASTODON_RETRY_DELAY)

            except MastodonNetworkError:
                # assume this is transient
                retry_counter += 1
                # pass

        if retry_counter >= MASTODON_RETRIES:
            logger.error("Retry limit reached.")
            return None

        return reply_to

    def transfer_attachments(self, post: Message) -> bool:

        # logger.debug(post.media_attachments)

        for attachment in post.media_attachments:

            attachment_url = attachment.get("url")
            attachment_desc = attachment.get("description")

            logger.info(f"Downloading {attachment_desc}  {attachment_url}")
            try:
                attachment_file = requests.get(attachment_url, stream=True)
                attachment_file.raw.decode_content = True
                temp_file = tempfile.NamedTemporaryFile(delete=False)
                temp_file.write(attachment_file.raw.read())
                temp_file.close()

            except (SSLError, ProtocolError, ConnectionError, OSError) as e:
                logger.error(f"{e}")
                raise MoaMediaUploadException("Connection Error downloading attachments")

            path = urlparse(attachment_url).path
            file_extension = splitext(path)[1]

            # file_extension = mimetypes.guess_extension(attachment_file.headers['Content-type'])

            # ffs
            if file_extension == '.jpe':
                file_extension = '.jpg'

            upload_file_name = temp_file.name + file_extension
            os.rename(temp_file.name, upload_file_name)

            # self.attachments.append((upload_file_name, attachment.ext_alt_text))

            logger.debug(f'Uploading {attachment_desc}: {upload_file_name}')

            try:
                self.media_ids.append(self.api.media_post(upload_file_name, description=attachment_desc))

            except (MastodonAPIError, MastodonUnauthorizedError) as e:
                logger.error(e)
                if 'Forbidden' in repr(e) or 'Unauthorized' in repr(e):
                    self.bridge.enabled = False
                raise MoaMediaUploadException("API Error uploading attachments") from e

            except (MastodonNetworkError, MastodonRatelimitError) as e:
                logger.error(e)
                raise MoaMediaUploadException("Connection Error uploading attachments") from e

            finally:
                os.unlink(upload_file_name)

        return True
