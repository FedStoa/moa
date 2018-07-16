import unittest

from moa.helpers import blacklisted


class TestBlacklist(unittest.TestCase):

    def setUp(self):
        self.tbl = [r'andri000me_.*']
        self.mbl = [r'magsberita.*', 'andriete']

    def test_black_list(self):

        self.assertEqual(blacklisted('andri000me_40', self.tbl), True)
        self.assertEqual(blacklisted('andri000me_12', self.tbl), True)
        self.assertEqual(blacklisted('magsberita', self.mbl), True)
        self.assertEqual(blacklisted('andriete', self.mbl), True)

        self.assertEqual(blacklisted('foozmeat', self.mbl), False)
