import html
import logging
import re
from datetime import datetime, timezone
from urllib.parse import urlparse

from moa.message import Message
from moa.models import CON_XP_ONLYIF, CON_XP_ONLYIF_TAGS, CON_XP_UNLESS, CON_XP_UNLESS_TAGS
from moa.tweet import HOUR_CUTOFF

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

    def __init__(self, settings, toot_data, config):

        super().__init__(settings, toot_data)

        self.content = None
        self.url_length = 23
        self.type = 'Toot'
        self.config = config

    def dump_data(self):
        return self.data

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
    def too_old(self) -> bool:
        now = datetime.now(timezone.utc)
        td = now - self.data['created_at']
        return td.total_seconds() >= 60 * 60 * HOUR_CUTOFF

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

        if self.too_old:
            logger.info(f'Skipping because >= {HOUR_CUTOFF} hours old.')
            return True

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

        elif self.settings.conditional_posting == CON_XP_ONLYIF:

            if not set(CON_XP_ONLYIF_TAGS) & self.data['tags']:
                logger.info(f'Skipping because {CON_XP_ONLYIF_TAGS} not found')
                return True

        elif self.settings.conditional_posting == CON_XP_UNLESS:
            local_tags = CON_XP_UNLESS_TAGS + ['nt']

            if set(local_tags) & set(self.data['tags']):
                logger.info(f'Skipping because {local_tags} found')
                return True

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

        status_length = len(string.encode('utf-16-le')) // 2

        match = re.findall(URL_REGEXP, string)
        if len(match) >= 1:
            replaced_chars = len(''.join(map(lambda x: x[0], match)))
            status_length = status_length - replaced_chars + (self.url_length * len(match))
            # logger.debug(f"{len(string)} {string} {status_length}")

        if self.is_sensitive and self.settings.post_sensitive_behind_link:
            status_length += len(f"\n{self.settings.sensitive_link_text}\n{self.url}")

        return status_length

    def sanitize_twitter_handles(self):
        self.content = re.sub(r'@?(\w{1,15})@twitter.com', '\g<1>', self.content)

        # find possible twitter handles so we can get their ranges
        tm = list(re.finditer(r'@(\w{1,15})', self.content))

        # find all masto handles so we can get their ranges
        mm = list(re.finditer(r'@\w+@[\w.]+', self.content))

        # find all masto profile links
        mm += list(re.finditer(r'https://[\w.]+/@[\w.]+', self.content))

        handles = set(tm)

        # remove all potential twitter handles that overlap a masto handle
        for m in mm:
            good_handles = set()
            ms = m.span()

            for t in tm:
                ts = t.span()

                # do the ranges overlap?
                overlap = not ((ts[-1] < ms[0]) or (ms[-1] < ts[0]))

                if overlap:
                    continue

                good_handles.add(t)

            handles = handles & good_handles

        handles = list(handles)
        handles = sorted(handles, key=lambda x: x.span()[0], reverse=True)

        for h in handles:
            front = self.content[:h.span()[0]]
            middle = h.group(1)
            back = self.content[h.span()[1]:]
            self.content = front + middle + back

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

            if self.config.SANITIZE_TWITTER_HANDLES:
                self.sanitize_twitter_handles()

            else:
                self.content = re.sub(r'@(\w{1,15})@twitter.com', '@\g<1>', self.content)

            self.content = self.content.strip()

            if self.spoiler_text:
                self.content = f"CW: {self.spoiler_text}\n\n{self.content}"

            if self.is_sensitive and self.settings.post_sensitive_behind_link and len(self.media_attachments) > 0:
                self.content = f"{self.content}\n{self.settings.sensitive_link_text}\n{self.url}"

            if self.is_boost:
                if len(self.content) > 0:
                    self.content = f"RT {self.boost_author}\n{self.content}\n{self.url}"
                else:
                    self.content = f"RT {self.boost_author}\n{self.url}\n"

            # logger.debug(self.content)

        return self.content

    def prepare_for_post(self, length=1):
        self.split_toot(length)

    def split_toot(self, max_length):

        self.message_parts = []
        part_n = 1

        expected_length = self.expected_status_length(self.clean_content)

        if expected_length <= max_length:
            self.message_parts.append(self.clean_content)

        else:

            current_part = ""
            words = self.clean_content.split(" ")

            if self.settings.split_twitter_messages:
                logger.info(f'Toot bigger than {max_length} characters, need to split...')

                for next_word in words:

                    possible_part = f"{current_part} {next_word}".lstrip()
                    length = self.expected_status_length(possible_part)

                    # logger.debug(f"length of possible part is {length}")

                    if length > max_length - 6:

                        current_part = f"{current_part} XXXXX".lstrip()

                        # logger.debug(f'Part is full ({self.expected_status_length(current_part)}):{current_part}')

                        self.message_parts.append(current_part)
                        current_part = next_word

                    else:
                        current_part = possible_part

                # Insert last part
                length = len(current_part.strip().encode('utf-8'))
                if length != 0:
                    current_part = f"{current_part} XXXXX".lstrip()
                    # logger.debug(f'Last Part ({self.expected_status_length(current_part)}):{current_part}')

                    self.message_parts.append(current_part.strip())

                for i, msg in enumerate(self.message_parts):
                    self.message_parts[i] = msg.replace('XXXXX', f"({i+1}/{len(self.message_parts)})")
                    logger.debug(self.message_parts[i])
            else:
                logger.info('Truncating toot')
                suffix = f"…\n{self.url}"
                tweet_length = max_length - len(suffix)
                truncated_text = self.clean_content[:tweet_length] + suffix

                logger.debug(f"Truncated Text length is {len(truncated_text)}")
                self.message_parts.append(truncated_text)
