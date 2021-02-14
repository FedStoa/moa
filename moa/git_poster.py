import logging
import requests
import re
import base64

from moa.poster import Poster
from moa.message import Message

logger = logging.getLogger('worker')

class GitPoster(Poster):
    def __init__(self, send, session, gitlab_host, bridge):

        super().__init__(send, session)

        # self.api = api
        self.bridge = bridge
        self.gitlab_host = gitlab_host

    def post(self, post: Message) -> bool:
        self.reset()

        reg = re.compile('\[\[push\]\] \[\[(.*?)\]\]*')
        m = reg.match(post.clean_content)
        if m is  None:
            logger.info("not found")
            return

        note = m.group(1)
        logger.info(post.clean_content)
        logger.info("FOUND NOTE FILE {}".format(note))
    
        
        # gitlab_host = app.config['GITLAB_HOST']
        access_token = self.bridge.gitlab_access_code
        file_info = requests.get('https://{}/api/v4/projects/23415794/repository/files/{}.md?access_token={}&ref=master'.format(self.gitlab_host, note, access_token))
        if file_info.status_code != 200:
            logger.info("bad request")
            return
        logger.info(file_info.status_code)
        encoded_content = file_info.json()['content']
        content = base64.standard_b64decode(encoded_content)
        logger.info(content)
        logger.info(file_info.json())
