import importlib
import logging
import os
import unittest

from moa.tweet_poster import TWEET_LENGTH
from tests.toot_samples import *
from moa.toot import Toot
from moa.settings import Settings


class TestToots(unittest.TestCase):

    def setUp(self):

        moa_config = os.environ.get('MOA_CONFIG', 'DevelopmentConfig')
        self.c = getattr(importlib.import_module('config'), moa_config)

        self.settings = Settings()

        FORMAT = '%(asctime)-15s %(message)s'
        logging.basicConfig(format=FORMAT)

        self.l = logging.getLogger('worker')
        self.l.setLevel(logging.DEBUG)

    def test_boost(self):

        toot = Toot(self.settings, boost, self.c)

        self.assertEqual(toot.is_boost, True)
        self.assertEqual(toot.is_reply, False)
        self.assertEqual(toot.should_skip, False)
        self.assertEqual(toot.boost_author, '@foozmeat@pdx.social')
        self.assertEqual(toot.clean_content, "RT @foozmeat@pdx.social\nRedis was a real a-hole today. I'm sad that we rely on it for job queues.\nhttps://pdx.social/@foozmeat/98965978733093918")

    def test_twitter_mention(self):

        toot = Toot(self.settings, twitter_mention, self.c)

        self.assertEqual(toot.is_boost, False)
        self.assertEqual(toot.is_reply, False)
        self.assertEqual(toot.should_skip, False)
        self.assertEqual(toot.clean_content, "mentioning @foozmeat here")

    def test_mention(self):

        toot = Toot(self.settings, toot_with_mention, self.c)

        self.assertEqual(toot.clean_content, "mentioning @foozmeat@pdx.social here")

    def test_double_mention(self):

        # with twitter sanitize
        toot = Toot(self.settings, toot_double_mention, self.c)
        self.assertEqual(toot.clean_content, "test 1 @moa_party@pdx.social\ntest 2 moa_party")

        # without
        self.c.SANITIZE_TWITTER_HANDLES = False
        toot = Toot(self.settings, toot_double_mention, self.c)
        self.assertEqual(toot.clean_content, "test 1 @moa_party@pdx.social\ntest 2 @moa_party")

    def test_cw(self):

        toot = Toot(self.settings, toot_with_cw, self.c)
        self.assertEqual(toot.clean_content, "CW: This is the spoiler text\n\nThis is the secret stuff")

    def test_length(self):
        toot = Toot(self.settings, toot_with_bogus_url, self.c)
        # print(toot.clean_content)
        expected_length = toot.expected_status_length(toot.clean_content)
        # print(expected_length)

        self.assertEqual(expected_length, 281)

    def test_truncation(self):
        self.settings.split_twitter_messages = False
        toot = Toot(self.settings, toot_incorrectly_truncated, self.c)
        toot.split_toot(TWEET_LENGTH)

        self.assertEqual('Has anyone written a story where the Amish play a crucial role in future society because they deliberately choose which technology they let in to their communities, and can therefore be safe “wake-up zones” for those cry…\nhttps://wandering.shop/@phildini/99434181894510181', toot.message_parts[0])
