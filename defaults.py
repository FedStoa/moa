class DefaultConfig(object):
    DEBUG = False
    DEVELOPMENT = False
    TESTING = False
    CSRF_ENABLED = True
    # secret key for flask sessions http://flask.pocoo.org/docs/1.0/quickstart/#sessions
    SECRET_KEY = 'this-really-needs-to-be-changed'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    TWITTER_CONSUMER_KEY = ''
    TWITTER_CONSUMER_SECRET = ''
    INSTAGRAM_CLIENT_ID = ''
    INSTAGRAM_SECRET = ''
    SQLALCHEMY_DATABASE_URI = 'sqlite:///moa.db'
    # SQLALCHEMY_DATABASE_URI = 'mysql+pymysql://moa:moa@localhost/moa'
    SEND = True
    SENTRY_DSN = ''
    HEALTHCHECKS = []
    MAIL_SERVER = None
    MAIL_PORT = 587
    MAIL_USE_TLS = True
    MAIL_USERNAME = ''
    MAIL_PASSWORD = ''
    MAIL_TO = ''
    MAIL_DEFAULT_SENDER = ''
    TWITTER_BLACKLIST = []
    MASTODON_BLACKLIST = []
    WORKER_JOBS = 1
    MAX_MESSAGES_PER_RUN = 5

    # This option prevents Twitter replies and mentions from occuring when a toot contains @user@twitter.com. This
    # behavior is against Twitter's rules.
    SANITIZE_TWITTER_HANDLES = True

    SEND_DEFERRED_EMAIL = False
    SEND_DEFER_FAILED_EMAIL = False
    MAINTENANCE_MODE = False

    STATS_POSTER_BASE_URL = None
    STATS_POSTER_ACCESS_TOKEN = None

    TRUST_PROXY_HEADERS = False
