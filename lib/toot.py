import html
import mimetypes
import re
import tempfile
from urllib.parse import urlparse
import logging

import os
import requests
import twitter
from twitter import twitter_utils, TwitterError

URL_REGEXP = re.compile((
                            r'('
                            r'(?!(https?://|www\.)?\.|ftps?://|([0-9]+\.){{1,3}}\d+)'  # exclude urls that start with "."
                            r'(?:https?://|www\.)*(?!.*@)(?:[\w+-_]+[.])'  # beginning of url
                            r'(?:{0}\b|'  # all tlds
                            r'(?:[:0-9]))'  # port numbers & close off TLDs
                            r'(?:[\w+\/]?[a-z0-9!\*\'\(\);:&=\+\$/%#\[\]\-_\.,~?])*'  # path/query params
                            r')').format(r'\b|'.join(twitter_utils.TLDS)), re.U | re.I | re.X)


logger = logging.getLogger('worker')


class Toot:
    content = None
    tweet_parts = []
    url_length = 23
    tweet_length = 140
    attachments = []

    def __init__(self, toot_data, settings):
        self.data = toot_data
        self.settings = settings

    @property
    def id(self):
        return self.data['id']

    @property
    def raw_content(self):
        return self.data['content']

    @property
    def is_reply(self):
        return self.data['in_reply_to_id'] is not None

    @property
    def is_boost(self):
        return self.data['reblog'] is not None

    @property
    def is_sensitive(self):
        return self.data['sensitive']

    @property
    def spoiler_text(self):
        return self.data['spoiler_text']

    @property
    def media_attachments(self):
        return self.data['media_attachments']

    @property
    def url(self):
        return self.data['url']

    @property
    def instance_url(self):
        o = urlparse(self.url)

        return f"{o.scheme}://{o.netloc}"

    @property
    def joined_tweet_parts(self):
        return "".join(self.tweet_parts)

    def expected_status_length(self, string):
        replaced_chars = 0
        status_length = len(string)
        match = re.findall(URL_REGEXP, string)
        if len(match) >= 1:
            replaced_chars = len(''.join(map(lambda x: x[0], match)))
            status_length = status_length - replaced_chars + (self.url_length * len(match))
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

            self.content = self.content.strip()

        return self.content

    def split_toot(self):
        expected_length = self.expected_status_length(self.clean_content)

        if expected_length < self.tweet_length:
            self.tweet_parts.append(self.clean_content)

        else:
            logger.info(f'Toot bigger {self.tweet_length} characters, need to split...')

            current_part = ""
            words = self.clean_content.split(" ")
            logger.debug(words)

            if self.settings.split_twitter_messages:

                for next_word in words:

                    possible_part = f"{current_part} {next_word}".lstrip()

                    if len(possible_part) > self.tweet_length - 3 :
                        logger.info(f'Part is full: {current_part}')

                        current_part = f"{current_part}…".lstrip()
                        self.tweet_parts.append(current_part)
                        current_part = next_word

                    else:
                        current_part = possible_part

                # Insert last part
                if len(current_part.strip()) != 0:
                    self.tweet_parts.append(current_part.strip())

            else:
                logger.info('Truncating toot')
                space_for_suffix = len('… ') + self.url_length
                self.tweet_parts.append(f"{current_part[:-space_for_suffix]}… {self.url}")
                current_part = ''

    def download_attachments(self):

        for attachment in self.media_attachments:
            attachment_url = attachment["url"]

            logger.info(f'Downloading {attachment_url}')
            attachment_file = requests.get(attachment_url, stream=True)
            attachment_file.raw.decode_content = True
            temp_file = tempfile.NamedTemporaryFile(delete=False)
            temp_file.write(attachment_file.raw.read())
            temp_file.close()

            file_extension = mimetypes.guess_extension(attachment_file.headers['Content-type'])
            upload_file_name = temp_file.name + file_extension
            os.rename(temp_file.name, upload_file_name)

            self.attachments.append(upload_file_name)

    def cleanup(self):

        for a in self.attachments:
            os.unlink(a)
