import html
import re
from urllib.parse import urlparse
import logging

import os
import requests

from moa.message import Message

MY_TLDS = [
    "shop"
]

URL_REGEXP = re.compile((
    r'('
    r'(?!(https?://|www\.)?\.|ftps?://|([0-9]+\.){{1,3}}\d+)'  # exclude urls that start with "."
    r'(?:https?://|www\.)*(?!.*@)(?:[\w+-_]+[.])'  # beginning of url
    r'(?:\w+'  # all tlds
    r'(?:[:0-9]*))'  # port numbers & close off TLDs
    r'(?:[/]?[?][a-z0-9!*\'();:&=+$/%#\[\]\-_.,~?]*)*'  # path/query params
    r')'), re.U | re.I | re.X)

logger = logging.getLogger('worker')


class Toot(Message):

    def __init__(self, toot_data, settings):

        super().__init__(settings)

        self.content = None
        self.url_length = 24
        self.tweet_length = 272  # be conservative so we dont split too near the end
        self.data = toot_data

    @property
    def id(self):
        return self.data['id']

    @property
    def visibility(self):
        return self.data['visibility']

    @property
    def in_reply_to_id(self):
        return self.data['in_reply_to_id']

    @property
    def raw_content(self):

        if self.is_boost:
            return self.data['reblog']['content']
        else:
            return self.data['content']

    @property
    def is_reply(self):
        _ = self.clean_content

        # This is kind of funky
        if len(self.content) > 0 and self.content[0] == '@':
            return True

        return self.data['in_reply_to_id'] is not None

    @property
    def is_self_reply(self):
        return self.is_reply and self.data['in_reply_to_account_id'] == self.data['account']['id']

    @property
    def is_boost(self):
        return self.data['reblog'] is not None

    @property
    def is_sensitive(self):
        if self.is_boost:
            return self.data['reblog']['sensitive']
        else:
            return self.data['sensitive']

    @property
    def spoiler_text(self):
        if self.is_boost:
            return self.data['reblog']['spoiler_text']
        else:
            return self.data['spoiler_text']

    @property
    def media_attachments(self):
        if self.is_boost:
            return self.data['reblog']['media_attachments']
        else:
            return self.data['media_attachments']

    @property
    def url(self):
        if self.is_boost:
            return self.data['reblog']['url']
        else:
            return self.data['url']

    @property
    def instance_url(self):
        o = urlparse(self.url)

        return f"{o.scheme}://{o.netloc}"

    @property
    def should_skip(self):

        if self.visibility == 'direct':
            logger.info(f'Skipping DM.')
            return True

        # Don't cross-post replies
        if self.is_reply and not self.is_self_reply:
            logger.info(f'Skipping reply.')
            return True

        if self.visibility == 'private' and not self.settings.post_private_to_twitter:
            logger.info(f'Skipping: Not Posting Private toots.')
            return True

        if self.visibility == 'unlisted' and not self.settings.post_unlisted_to_twitter:
            logger.info(f'Skipping: Not Posting Unlisted toots.')
            return True

        if self.is_boost and not self.settings.post_boosts_to_twitter:
            logger.info(f'Skipping: not posting boosts')
            return True
        elif self.is_boost and self.settings.post_boosts_to_twitter:
            # If it's a boost and boosts are allowed then post it even
            # if public toots aren't allowed
            pass
        else:
            if self.visibility == 'public' and not self.settings.post_to_twitter:
                logger.info(f'Skipping: Not Posting Public toots.')
                return True

        return False

    @property
    def mentions(self):

        mentions = []
        for m in self.data['mentions']:

            o = urlparse(m['url'])

            mentions.append((m['username'], f"@{m['username']}@{o.netloc}"))

        return mentions

    @property
    def boost_author(self):

        if not self.is_boost:
            return None

        a = self.data['reblog']['account']
        o = urlparse(a['url'])

        return f"@{a['username']}@{o.netloc}"

    @property
    def joined_tweet_parts(self):
        return "".join(self.message_parts)

    def expected_status_length(self, string):

        status_length = len(string.encode('utf-8'))
        match = re.findall(URL_REGEXP, string)
        if len(match) >= 1:
            replaced_chars = len(''.join(map(lambda x: x[0], match)))
            status_length = status_length - replaced_chars + (self.url_length * len(match))
            # logger.debug(f"{len(string)} {string} {status_length}")
        return status_length

    @property
    def clean_content(self):

        media_regexp = re.compile(re.escape(self.instance_url) + "\/media\/[\w-]+\s?")

        if not self.content:

            self.content = self.raw_content

            # We trust mastodon to return valid HTML
            self.content = re.sub(r'<a [^>]*href="([^"]+)">[^<]*</a>', '\g<1>', self.content)

            # We replace html br with new lines
            self.content = "\n".join(re.compile(r'<br ?/?>', re.IGNORECASE).split(self.content))

            # We must also replace new paragraphs with double line skips
            self.content = "\n\n".join(re.compile(r'</p><p>', re.IGNORECASE).split(self.content))

            # Then we can delete the other html contents and unescape the string
            self.content = html.unescape(str(re.compile(r'<.*?>').sub("", self.content).strip()))

            # Trim out media URLs
            self.content = re.sub(media_regexp, "", self.content)

            # fix up masto mentions
            for mention in self.mentions:
                self.content = re.sub(f'@({mention[0]})(?!@)', f"{mention[1]}", self.content)

            self.content = re.sub(r'@(\w+)@twitter.com', '@\g<1>', self.content)

            self.content = self.content.strip()

            if self.spoiler_text:
                self.content = f"CW: {self.spoiler_text}\n\n{self.content}"

            if self.is_boost:
                if len(self.content) > 0:
                    self.content = f"RT {self.boost_author}\n{self.content}\n{self.url}"
                else:
                    self.content = f"RT {self.boost_author}\n{self.url}\n"

            # logger.debug(self.content)

        return self.content

    def prepare_for_post(self):
        self.split_toot()

    def split_toot(self):

        self.message_parts = []

        expected_length = self.expected_status_length(self.clean_content)

        if expected_length < self.tweet_length:
            self.message_parts.append(self.clean_content)

        else:

            current_part = ""
            words = self.clean_content.split(" ")

            if self.settings.split_twitter_messages:
                logger.info(f'Toot bigger than {self.tweet_length} characters, need to split...')

                for next_word in words:

                    possible_part = f"{current_part} {next_word}".lstrip()
                    length = self.expected_status_length(possible_part)

                    # logger.debug(f"length of possible part is {length}")

                    if length > self.tweet_length - 3:
                        logger.debug(f'Part is full ({self.expected_status_length(current_part)}):{current_part}')

                        current_part = f"{current_part}…".lstrip()
                        self.message_parts.append(current_part)
                        current_part = next_word

                    else:
                        current_part = possible_part

                # Insert last part
                length = len(current_part.strip().encode('utf-8'))
                if length != 0:
                    logger.debug(f'{length} {current_part}')
                    self.message_parts.append(current_part.strip())

            else:
                logger.info('Truncating toot')
                suffix = f"…\n{self.url}"
                tweet_length = self.tweet_length - len(suffix)
                truncated_text = self.clean_content[:tweet_length] + suffix

                logger.debug(f"Truncated Text length is {len(truncated_text)}")
                self.message_parts.append(truncated_text)

