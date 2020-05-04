import importlib
import logging
import os
import unittest
import twitter
import json

from twitter import UserStatus, Status

from moa.tweet import Tweet
from moa.models import TSettings

"""
To add a new test tweet stop the worker in the debugger and call self.dump_data() and copy the JSON result
"""


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
                tweet_mode='extended',  # Allow tweets longer than 140 raw characters

                # Get these 2 from the bridge
                access_token_key=self.c.TWITTER_OAUTH_TOKEN,
                access_token_secret=self.c.TWITTER_OAUTH_SECRET,
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

        expected_content = 'RT @lorddeath@twitter\nTbh I need to find time to email @aaisp@twitter and be prepared to do some troubleshooting, as my “@a@twitter.1” line drops pretty much daily :( Even @aaisp@twitter can\'t force BT OpenReach to give me fully-stable lines :p'

        self.assertEqual(expected_content, tweet.clean_content)

    def test_mention_replacement_1(self):
        status = self.thaw_tweet('mention_replacement_1')

        tweet = Tweet(self.settings, status, self.api)
        expected_content = '#booster2019 was another great time. Lovely city, on-point organization (food, coffee), awesome talks & crowd (including an evolter, @MartinBurnsSCO@twitter).'

        self.assertEqual(expected_content, tweet.clean_content)

    def test_rt_with_entity_1(self):
        status = self.thaw_tweet('rt_with_entity_1')

        tweet = Tweet(self.settings, status, self.api)
        expected_content = '+1 \n---\nRT @lisacrispin@twitter\nThanks again to all the wonderful, welcoming people who made @boosterconf@twitter amazing. Umbrellas, great food, perfect mix of session types & lengths, great diversity, wide range of topics, so fun. #booster2019 💜\nhttps://twitter.com/lisacrispin/status/1106754071233552384'

        self.assertEqual(expected_content, tweet.clean_content)

    def test_quote_tweet_mention_mangle_1(self):

        status = self.thaw_tweet('quote_tweet_mention_mangle_1')

        tweet = Tweet(self.settings, status, self.api)

        expected_content = """Say no to spec work.
https://euronews.com/2019/04/15/fire-underway-at-notre-dame-cathedral-in-paris-firefighters-say
Source: https://twitter.com/EPhilippePM/status/1118472220509126661
cc @nospec@twitter
---
RT @EPhilippePM@twitter
Faut-il reconstruire une flèche ? À l’identique ? Adaptée aux techniques et aux enjeux de notre époque ? Un concours international d’architecture portant sur la reconstruction de la flèche de la cathédrale ser…
https://twitter.com/EPhilippePM/status/1118472220509126661"""

        self.assertEqual(expected_content, tweet.clean_content)

