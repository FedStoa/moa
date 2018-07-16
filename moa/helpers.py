import re


def blacklisted(name, bl):

    for p in bl:
        if re.match(p, name):
            return True

    return False
