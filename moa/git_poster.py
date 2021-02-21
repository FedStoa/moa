import logging
import requests
import re
import base64
from datetime import datetime

from moa.poster import Poster
from moa.message import Message

logger = logging.getLogger('worker')

class GitPoster(Poster):
    def __init__(self, send, session, gitlab_host, bridge):

        super().__init__(send, session)

        self.bridge = bridge
        self.gitlab_host = gitlab_host

    def post(self, post: Message) -> bool:
        self.reset()


        logger.info('Post body: {}'.format(post.clean_content))
        reg = re.compile('.*\[\[.*?\]\]')
        m = reg.match(post.clean_content)
        if m is None:
            logger.info("no wikilink found in post")
            return
            
        date = datetime.now().date().isoformat()
        access_token = self.bridge.gitlab_access_code
        url = 'https://{}/api/v4/projects/{}/repository/files/{}.md'.format(self.gitlab_host, self.bridge.t_settings.gitlab_project, date)
        raw_url = '{}/raw?ref=master&access_token={}'.format(url, access_token)
        raw = requests.get(raw_url)
        # logger.info(raw.text)
        if raw.status_code == 200:
            content = '{}\n\n{}'.format(raw.text, post.clean_content)
            file_info = requests.put(url, data={'branch': 'master', 'content': content, 'commit_message': 'update from moa', 'access_token': access_token})
        else:
            content = '{}'.format(post.clean_content)
            file_info = requests.post(url, data={'branch': 'master', 'content': content, 'commit_message': 'update from moa', 'access_token': access_token})
        # logger.info(content)
        if file_info.status_code != 200:
            logger.info(file_info.text)
            return
        logger.info(file_info.status_code)

