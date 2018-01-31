```
                 _ __ ___   ___   __ _
                | '_ ` _ \ / _ \ / _` |
                | | | | | | (_) | (_| |
                |_| |_| |_|\___/ \__,_| (Beta)

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

A Mastodon <-> Twitter Cross-poster

https://moa.party

## Install

#### Requires python 3 (tested with python 3.6)

Moa is a flask app and can be run with `python` or proxied behind something like nginx/passenger.

* clone it
* make a virtual environment `python3 -m venv .moa-venv`
* activate `source .moa-venv/bin/activate`
* `pip install -r requirements.txt`
* `cp config.py.sample config.py` and fill in the blanks
* python app.py
* run the worker with `python -m moa.worker`

## Features
* preserves image alt text
* handles boosts/retweets

Some code lifted from https://github.com/halcy/MastodonToTwitter


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
    passenger_python /var/www/moa/.moa-venv/bin/python3;
    passenger_env_var MOA_CONFIG config.ProductionConfig;
    
    root /var/www/moa/public;
}
```

![](static/madewpc.gif)
