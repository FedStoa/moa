import logging
import mimetypes
import os
import platform
import pprint as pp
import subprocess
import tempfile
import time
from typing import Optional

import requests
from requests.exceptions import SSLError
from twitter import TwitterError
from urllib3.exceptions import ProtocolError, NewConnectionError, ConnectionError

from moa.helpers import MoaMediaUploadException
from moa.message import Message
from moa.models import Mapping
from moa.poster import Poster

logger = logging.getLogger('worker')
TWITTER_RETRIES = 3
TWITTER_RETRY_DELAY = 5
TWEET_LENGTH = 280


class TweetPoster(Poster):

    def __init__(self, send, session, api, bridge):

        super().__init__(send, session)

        self.api = api
        self.bridge = bridge

    def post(self, post: Message) -> bool:

        self.reset()

        if post.should_skip:
            return False

        logger.info(f"TweetPoster Working on {post.type} {post.id}")
        # logger.debug(pp.pformat(post.dump_data()))

        post.prepare_for_post(length=TWEET_LENGTH)

        if self.send:

            if post.is_sensitive and self.bridge.t_settings.post_sensitive_behind_link:
                pass
            else:
                self.transfer_attachments(post)

            reply_to = None

            if post.is_self_reply:

                # In the case where a toot has been broken into multiple tweets
                # we want the last one posted
                mapping = self.session.query(Mapping).filter_by(mastodon_id=post.in_reply_to_id).order_by(
                        Mapping.created.desc()).first()

                if mapping:
                    reply_to = mapping.twitter_id
                    logger.info(f"Replying to Twitter status {reply_to} / masto status {post.in_reply_to_id}")
                else:
                    # we don't know about this message which means it wasn't posted so let's skip it
                    logger.info("Skipping reply to unknown message")
                    return False

            last_id = len(post.message_parts) - 1
            for index, status in enumerate(post.message_parts):

                # Do normal posting for all but the last tweet where we need to upload media
                if index == last_id:
                    reply_to = self.send_tweet(status, reply_to, self.media_ids)

                else:
                    reply_to = self.send_tweet(status, reply_to)

                if reply_to:
                    self.bridge.twitter_last_id = reply_to
                    logger.info(f"Tweet ID: {reply_to}")

                    if post.type == "Toot":
                        m = Mapping()
                        m.mastodon_id = post.id
                        m.twitter_id = reply_to
                        self.session.add(m)
                else:
                    return False

                if post.type == "Toot":
                    self.bridge.mastodon_last_id = post.id

                self.session.commit()

            return True
        else:
            # logger.info(post.media_attachments)
            logger.info(post.clean_content)
            return False

    def send_tweet(self, status_text, reply_to, media_ids=None) -> Optional[int]:
        retry_counter = 0
        post_success = False

        while not post_success and retry_counter < TWITTER_RETRIES:

            logger.info(f'Tweeting "{status_text}"')

            if self.media_ids:
                logger.info(f'With media')

            try:
                reply_to = self.api.PostUpdate(status_text,
                                               media=media_ids,
                                               in_reply_to_status_id=reply_to,
                                               verify_status_length=False).id
                post_success = True

            except TwitterError as e:
                logger.error(e.message)

                if e.message[0]['code'] == 187:
                    # Status is a duplicate
                    return None
                elif e.message[0]['code'] == 186:
                    # Status is too long. Nowadays this happens because of UTF-8 text.
                    return None

                elif e.message[0]['code'] == 144:
                    # tweet being replied to is gone
                    return None
                elif e.message[0]['code'] in [64, 89]:
                    logger.warning(f"Disabling bridge for Twitter user @{self.bridge.twitter_handle}")
                    self.bridge.twitter_oauth_token = None
                    self.bridge.twitter_oauth_secret = None
                    self.bridge.enabled = False
                    return None

                if retry_counter < TWITTER_RETRIES:
                    retry_counter += 1
                    time.sleep(TWITTER_RETRY_DELAY)

        if retry_counter == TWITTER_RETRIES:
            logger.error("Retry limit reached.")
            return None

        return reply_to

    def transfer_attachments(self, post: Message):
        # logger.debug(post.media_attachments)

        for attachment in post.media_attachments:
            attachment_url = attachment.get("url")

            logger.info(f'Downloading {attachment_url}')

            try:
                attachment_file = requests.get(attachment_url, stream=True)
                attachment_file.raw.decode_content = True

                temp_file = tempfile.NamedTemporaryFile(delete=False)
                temp_file.write(attachment_file.raw.read())
                temp_file.close()

            except (SSLError, ProtocolError, ConnectionError, NewConnectionError) as e:
                logger.error(f"{e}")
                raise MoaMediaUploadException("Connection Error fetching attachments")

            fsize = os.path.getsize(temp_file.name)

            if fsize == 0:
                logger.error("Attachment is 0 length...skipping")
                continue

            file_extension = mimetypes.guess_extension(attachment_file.headers['Content-type'])

            # ffs
            if file_extension == '.jpe':
                file_extension = '.jpg'
            elif file_extension is None:
                file_extension = ''

            upload_file_name = temp_file.name + file_extension
            os.rename(temp_file.name, upload_file_name)

            if file_extension == '.webm':
                converted_file_name = temp_file.name + '.mp4'
                if platform.system() == 'Darwin':
                    FFMPEG = '/usr/local/bin/ffmpeg'
                else:
                    FFMPEG = '/usr/bin/ffmpeg'

                return_code = subprocess.call([FFMPEG,
                                               '-loglevel', 'error',
                                               '-xerror',
                                               '-i', upload_file_name,
                                               '-y',
                                               converted_file_name])
                os.unlink(upload_file_name)

                if return_code == 0:
                    upload_file_name = converted_file_name

            description = attachment.get('description', "")
            # self.attachments.append((upload_file_name, description))

            temp_file_read = open(upload_file_name, 'rb')
            logger.info(f'Uploading {description} {upload_file_name}')

            try:
                if file_extension in ['.webm', '.mp4', '.mov']:
                    media_id = self.api.UploadMediaChunked(media=temp_file_read,
                                                           media_category='tweet_video')
                else:
                    media_id = self.api.UploadMediaChunked(media=temp_file_read)

                if description:
                    self.api.PostMediaMetadata(media_id, alt_text=description)

                self.media_ids.append(media_id)

            except (TwitterError, ConnectionError, NewConnectionError) as e:
                logger.error(f"Twitter upload error: {e.message}")
                raise MoaMediaUploadException("Connection Error uploading attachments")

            finally:
                temp_file_read.close()
                os.unlink(upload_file_name)
        return True
