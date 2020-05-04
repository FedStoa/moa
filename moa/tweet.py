import html
import json
import logging
import re
from datetime import datetime, timezone

import requests
from twitter import TwitterError
from urllib3.exceptions import NewConnectionError
from requests import ConnectionError

from moa.helpers import MoaMediaUploadException
from moa.message import Message
from moa.models import CON_XP_ONLYIF, CON_XP_ONLYIF_TAGS, CON_XP_UNLESS, CON_XP_UNLESS_TAGS

logger = logging.getLogger('worker')

HOUR_CUTOFF = 8
HANDLE_SUFFIX = ''


class Tweet(Message):
    def __init__(self, settings, data, api):

        super().__init__(settings, data)

        self.__fetched_attachments = None
        self.__content = None
        self.api = api
        self.type = 'Tweet'

    @property
    def id(self) -> int:
        return self.data.id

    def dump_data(self):
        return json.dumps(self.data._json)

    @property
    def created_at(self):
        return datetime.strptime(self.data.created_at, '%a %b %d %H:%M:%S %z %Y')

    @property
    def too_old(self) -> bool:
        now = datetime.now(timezone.utc)
        td = now - self.created_at
        return td.total_seconds() >= 60 * 60 * HOUR_CUTOFF

    @property
    def media(self):

        if not self.__fetched_attachments:

            if self.is_retweet:
                target_id = self.data.retweeted_status.id

            elif self.is_quoted:

                if self.data.media and len(self.data.media) > 0:
                    # Does the user's tweet have media?
                    target_id = self.data.id
                else:
                    # If not, use the media from the quoted tweet
                    target_id = self.data.quoted_status.id

            else:
                target_id = self.data.id

            try:
                fetched_tweet = self.api.GetStatus(
                        status_id=target_id,
                        trim_user=True,
                        include_my_retweet=False,
                        include_entities=True,
                        include_ext_alt_text=True
                )
                self.__fetched_attachments = fetched_tweet.media

            except (TwitterError, ConnectionError) as e:
                logger.error(e)

            if not self.__fetched_attachments:
                self.__fetched_attachments = []

        return self.__fetched_attachments

    @property
    def should_skip(self):

        if self.too_old:
            logger.info(f'Skipping because >= {HOUR_CUTOFF} hours old.')
            return True

        if self.is_reply:
            logger.info(f'Skipping reply.')
            return True

        if self.is_quoted and not self.settings.post_quotes_to_mastodon:
            logger.info(f'Skipping quoted tweets.')
            return True

        if self.is_retweet and not self.settings.post_rts_to_mastodon:
            logger.info(f'Skipping retweet.')
            return True

        if self.is_retweet and self.settings.post_rts_to_mastodon:
            # Posting retweets
            pass

        elif self.settings.conditional_posting == CON_XP_ONLYIF:

            twitter_hts = set([h.text for h in self.data.hashtags])
            if not set(CON_XP_ONLYIF_TAGS) & twitter_hts:
                logger.info(f'Skipping because {CON_XP_ONLYIF_TAGS} not found')
                return True

        elif self.settings.conditional_posting == CON_XP_UNLESS:
            twitter_hts = set([h.text for h in self.data.hashtags])
            local_tags = CON_XP_UNLESS_TAGS + ['nm']

            if set(local_tags) & twitter_hts:
                logger.info(f'Skipping because {local_tags} found')
                return True

        if not self.settings.post_to_mastodon:
            logger.info(f'Skipping regular tweets.')
            return True

        return False

    @property
    def url(self):
        base = "https://twitter.com"
        user = self.data.user.screen_name
        status = self.data.id

        if self.is_retweet:
            user = self.data.retweeted_status.user.screen_name
            status = self.data.retweeted_status.id

        elif self.is_quoted:
            user = self.data.quoted_status.user.screen_name
            status = self.data.quoted_status.id

        return f"{base}/{user}/status/{status}"

    @property
    def is_retweet(self):
        return self.data.retweeted_status is not None

    @property
    def is_quoted(self):
        return self.data.quoted_status is not None

    @property
    def is_reply(self):

        if self.data.in_reply_to_screen_name is not None:

            if not self.is_self_reply or self.data.full_text[0] == '@':
                return True

    @property
    def in_reply_to_id(self):
        return self.data.in_reply_to_status_id

    @property
    def is_self_reply(self):
        return self.data.in_reply_to_user_id == self.data.user.id

    @property
    def urls(self):
        if self.is_retweet:
            return self.data.retweeted_status.urls
        elif self.is_quoted:
            return self.data.quoted_status.urls
        else:
            return self.data.urls

    @property
    def is_sensitive(self):
        return bool(self.data.possibly_sensitive)

    @property
    def mentions(self):

        if self.is_retweet:
            m = [(u.screen_name, u._json['indices']) for u in self.data.retweeted_status.user_mentions]
        else:
            m = [(u.screen_name, u._json['indices']) for u in self.data.user_mentions]

        return m

    @property
    def quoted_mentions(self):

        if self.data.quoted_status:
            m = [(u.screen_name, u._json['indices']) for u in self.data.quoted_status.user_mentions]

        return m

    def expand_handles(self, content, mentions):

        if content:

            if mentions:
                index = 0
                rt_pad = 0

                for mention, indices in mentions:

                    pad = (index * len(HANDLE_SUFFIX)) - rt_pad
                    s = indices[0] + pad
                    e = indices[1] + pad
                    replacement = f"@{mention}{HANDLE_SUFFIX}"

                    content = content[:s] + replacement + content[e:]

                    index += 1
        return content

    @property
    def clean_content(self):

        quoted_text = None
        cw_regex = r'[TtCc][Ww]: (.*)\n'

        if not self.__content:

            if self.is_retweet:
                content = self.data.retweeted_status.full_text
                content = self.expand_handles(content, self.mentions)

            elif self.is_quoted:
                content = self.data.full_text

                # Handles have to be expanded before URLs are unfurled or the indices
                # will be wrong
                content = self.expand_handles(content, self.mentions)

                for url in self.data.urls:
                    # Unshorten URLs
                    content = re.sub(url.url, url.expanded_url, content)

                # remove the trailing URL of the quoted tweet
                content = re.sub(r'https://twitter.com/.*$', '', content)

                quoted_text = self.data.quoted_status.full_text
                quoted_text = self.expand_handles(quoted_text, self.quoted_mentions)
                quoted_text = html.unescape(quoted_text)

                for url in self.data.quoted_status.urls:
                    # Unshorten URLs
                    quoted_text = re.sub(url.url, url.expanded_url, quoted_text)

            else:
                content = self.data.full_text
                content = self.expand_handles(content, self.mentions)

                m = re.search(cw_regex, content)

                if m:
                    whole_cw = m.group(0)
                    content = content.replace(whole_cw, '').strip()
                    self.cw = m.group(1)

            content = html.unescape(content)

            for url in self.urls:
                # Unshorten URLs
                content = re.sub(url.url, url.expanded_url, content)

            if self.is_retweet:
                if len(content) > 0:
                    content = f"RT @{self.data.retweeted_status.user.screen_name}{HANDLE_SUFFIX}\n{content}"
                else:
                    content = f"RT @{self.data.retweeted_status.user.screen_name}{HANDLE_SUFFIX}\n"

            elif self.is_quoted:
                for attachment in self.media:
                    # Remove the t.co link to the media
                    quoted_text = re.sub(attachment.url, "", quoted_text)

                possible_content = f"{content}\n---\nRT @{self.data.quoted_status.user.screen_name}{HANDLE_SUFFIX}\n{quoted_text}\n{self.url}"

                if len(possible_content) > 500:
                    logger.info(f"Toot is too long: {len(possible_content)}")
                    diff = len(possible_content) - 500 + 1
                    quoted_text = quoted_text[:-diff]
                    content = f"{content}\n---\nRT @{self.data.quoted_status.user.screen_name}{HANDLE_SUFFIX}\n{quoted_text}…\n{self.url}"
                    logger.info(f"Length is now: {len(content)}")

                else:
                    content = possible_content

            for attachment in self.media:
                # Remove the t.co link to the media
                content = re.sub(attachment.url, "", content)

            if len(content) == 0:
                logger.info("Content is empty - adding unicode character.")
                content = u"\u2063"

            self.__content = content
        return self.__content

    def prepare_for_post(self, length=1):

        self.message_parts.append(self.clean_content)

    @property
    def media_attachments(self):

        attachments = []

        for attachment in self.media:
            # logger.debug(attachment.__dict__)

            type = attachment.type
            attachment_url = None

            if type in ['video', 'animated_gif']:

                variants = attachment.video_info['variants'].copy()
                variants.reverse()

                # logger.debug(variants)

                index = 0
                max = len(variants) - 1

                while not attachment_url and index <= max:
                    logger.info(f"Examining attachment variant {index}")

                    if 'bitrate' not in variants[index]:
                        logger.info(f"Missing bitrate")

                        attachment_url = None
                        index += 1

                        if index > max:
                            continue

                    attachment_url = variants[index]['url']

                    try:
                        response = requests.head(attachment_url)

                        if response.ok:
                            size = int(response.headers['content-length'])

                            if size > (8 * 1024 * 1024):
                                logger.info(f"Too large")
                                attachment_url = None
                                index += 1

                                if index > max:
                                    continue
                        else:
                            attachment_url = None
                            index += 1

                            if index > max:
                                continue

                    except (ConnectionError, NewConnectionError) as e:
                        logger.error(f"{e}")
                        attachment_url = None
                        raise MoaMediaUploadException("Connection Error fetching attachments")

            else:
                attachment_url = attachment.media_url

            if attachment_url:
                attachments.append({'url':         attachment_url,
                                    'description': attachment.ext_alt_text})

        return attachments
