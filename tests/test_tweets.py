import importlib
import logging
import os
import unittest
import twitter
import json

from twitter import UserStatus, Status

from moa.tweet import Tweet
from moa.models import TSettings


class TestTweets(unittest.TestCase):

    def setUp(self):
        moa_config = os.environ.get('MOA_CONFIG', 'TestingConfig')
        self.c = getattr(importlib.import_module('config'), moa_config)

        self.settings = TSettings()

        FORMAT = '%(asctime)-15s %(message)s'
        logging.basicConfig(format=FORMAT)

        self.l = logging.getLogger()
        self.l.setLevel(logging.INFO)

        self.api = twitter.Api(
                consumer_key=self.c.TWITTER_CONSUMER_KEY,
                consumer_secret=self.c.TWITTER_CONSUMER_SECRET,
                access_token_key=self.c.TWITTER_OAUTH_TOKEN,
                access_token_secret=self.c.TWITTER_OAUTH_SECRET,
                tweet_mode='extended'  # Allow tweets longer than 140 raw characters
        )

    def thaw_tweet(self, name):
        with open(f'tests/twitter_json/{name}.json', 'r') as f:
            data = f.read()
        obj = json.loads(data)
        status = Status.NewFromJsonDict(obj)
        return status

    def test_rt_with_mentions(self):

        status = self.thaw_tweet('retweet_with_mentions')

        tweet = Tweet(self.settings, status, self.api)

        expected_content = 'RT @lorddeath@twitter.com\nTbh I need to find time to email @aaisp@twitter.com and be prepared to do some troubleshooting, as my “@a@twitter.com.1” line drops pretty much daily :( Even @aaisp@twitter.com can\'t force BT OpenReach to give me fully-stable lines :p'

        self.assertEqual(expected_content, tweet.clean_content)

    def test_mention_replacement_1(self):
        status = self.thaw_tweet('mention_replacement_1')

        tweet = Tweet(self.settings, status, self.api)
        expected_content = '#booster2019 was another great time. Lovely city, on-point organization (food, coffee), awesome talks & crowd (including an evolter, @MartinBurnsSCO@twitter.com).'

        self.assertEqual(expected_content, tweet.clean_content)

    def test_rt_with_entity_1(self):
        status = self.thaw_tweet('rt_with_entity_1')

        tweet = Tweet(self.settings, status, self.api)
        expected_content = '+1 \n---\nRT @lisacrispin@twitter.com\nThanks again to all the wonderful, welcoming people who made @boosterconf amazing. Umbrellas, great food, perfect mix of session types & lengths, great diversity, wide range of topics, so fun. #booster2019 💜\nhttps://twitter.com/lisacrispin/status/1106754071233552384'

        self.assertEqual(expected_content, tweet.clean_content)
