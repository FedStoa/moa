Hello! We are prepping to run Moa as a public utility!

Thank you to [James Moore](https://jmoore.me/) as the original creator and maintainer of both the code and the public service.

Join us on Matrix chat [#moaparty:matrix.org](https://matrix.to/#/!zPwMsygFdoMjtdrDfo:matrix.org?via=matrix.org) to get involved, or file an issue here.

```
                 _ __ ___   ___   __ _
                | '_ ` _ \ / _ \ / _` |
                | | | | | | (_) | (_| |
                |_| |_| |_|\___/ \__,_|

┌──────────────┐     ╔══════════════╗      ┌──────────────┐
│  Instagram   │────▶║  moa.party   ║◀────▶│   Twitter    │
└──────────────┘     ╚══════════════╝      └──────────────┘
                             ▲
                             │
                             ▼
                     ┌──────────────┐
                     │   Mastodon   │
                     └──────────────┘
```

Link your Mastodon account to Twitter and Instagram

https://moa.party

## Install

#### Requires python 3.6+

Moa is a flask app and can be run with `python` or proxied via WSGI.

* clone it
* On Debian/Ubuntu you'll need to `apt install python-dev python3-dev build-essential`
* Install pipenv `pip3 install pipenv`
* `PIPENV_VENV_IN_PROJECT=1 pipenv install`
* `cp config.py.sample config.py` and override the settings from `defaults.py`
* `MOA_CONFIG=config.DevelopmentConfig pipenv run python -m moa.models` to create the DB tables
* `MOA_CONFIG=config.DevelopmentConfig pipenv run python app.py`
* run the worker with `MOA_CONFIG=DevelopmentConfig pipenv run python -m moa.worker`

## Features
* preserves image alt text
* handles boosts/retweets

Some code lifted from https://github.com/halcy/MastodonToTwitter

## Twitter App setup

If you plan to use twitter then you'll need to create a twitter app first so the required crednetials can be obtained.

* Follow the steps here to get started https://python-twitter.readthedocs.io/en/latest/getting_started.html
* For the Callback URL use [moa_base_url]/twitter_oauthorized e.g. https://example.com/twitter_oauthorized
* Access Permissions need to be "read" and "write"


## Example nginx/passenger configuration

```
server {
    listen 80;
    server_name moa.party;
    return 301 https://$server_name$request_uri;
}

server {
    listen 443 ;
    server_name moa.party;
    
    # SSL
    
    ssl on;
    ssl_certificate     /etc/certificates/moa.crt;
    ssl_certificate_key /etc/certificates/moa.key;
    
    client_max_body_size 1G;
    
    access_log /var/www/moa/logs/access.log;
    error_log /var/www/moa/logs/error.log;
    
    location = /favicon.ico { log_not_found off; access_log off; }
    location = /robots.txt  { log_not_found off; access_log off; }
    
    passenger_enabled on;
    passenger_app_env production;
    passenger_python /var/www/moa/.venv/bin/python3;
    passenger_env_var MOA_CONFIG config.ProductionConfig;
    
    root /var/www/moa/public;
}
```

![](static/madewpc.gif)
