import unittest

from tests.toot_samples import *
from tests.tweet_samples import *
from toot import Toot
from settings import Settings


class TestToots(unittest.TestCase):

    def test_boost(self):

        settings = Settings()

        toot = Toot(boost, settings)

        self.assertEqual(toot.is_boost, True)
        self.assertEqual(toot.is_reply, False)
        self.assertEqual(toot.should_skip, False)
        self.assertEqual(toot.boost_author, '@foozmeat@pdx.social')
        self.assertEqual(toot.clean_content, "RT @foozmeat@pdx.social\nRedis was a real a-hole today. I'm sad that we rely on it for job queues.\nhttps://pdx.social/@foozmeat/98965978733093918")

    def test_twitter_mention(self):

        settings = Settings()

        toot = Toot(twitter_mention, settings)

        self.assertEqual(toot.is_boost, False)
        self.assertEqual(toot.is_reply, False)
        self.assertEqual(toot.should_skip, False)
        self.assertEqual(toot.clean_content, "mentioning @foozmeat here")

    def test_mention(self):

        settings = Settings()

        toot = Toot(toot_with_mention, settings)

        self.assertEqual(toot.clean_content, "mentioning @foozmeat@pdx.social here")

    def test_double_mention(self):

        settings = Settings()

        toot = Toot(toot_double_mention, settings)

        self.assertEqual(toot.clean_content, "test 1 @moa_party@pdx.social\ntest 2 @moa_party")

    def test_cw(self):

        settings = Settings()

        toot = Toot(toot_with_cw, settings)

        self.assertEqual(toot.clean_content, "CW: This is the spoiler text\n\nThis is the secret stuff")
