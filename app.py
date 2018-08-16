import logging
import os
from datetime import datetime, timedelta
from logging.handlers import TimedRotatingFileHandler

import pandas as pd
import pygal
import twitter
from flask import Flask, flash, g, redirect, render_template, request, session, url_for
from flask_mail import Mail, Message
from flask_migrate import Migrate
from flask_oauthlib.client import OAuth, OAuthException
from flask_sqlalchemy import SQLAlchemy
from instagram.client import InstagramAPI
from instagram.helper import datetime_to_timestamp
from mastodon import Mastodon
from mastodon.Mastodon import MastodonAPIError, MastodonIllegalArgumentError, MastodonNetworkError
from sqlalchemy import exc, func

from moa.forms import MastodonIDForm, SettingsForm
from moa.helpers import blacklisted
from moa.models import Bridge, MastodonHost, WorkerStat, metadata
from moa.settings import Settings

app = Flask(__name__)

FORMAT = "%(asctime)-15s [%(filename)s:%(lineno)s : %(funcName)s()] %(message)s"

formatter = logging.Formatter(FORMAT)

# initialize the log handler
logHandler = TimedRotatingFileHandler('logs/app.log', when='D', backupCount=7)
logHandler.setFormatter(formatter)

# set the log handler level
logHandler.setLevel(logging.INFO)

# set the app logger level
app.logger.setLevel(logging.INFO)

app.logger.addHandler(logHandler)

app.logger.info("Starting up...")

config = os.environ.get('MOA_CONFIG', 'config.DevelopmentConfig')
app.config.from_object(config)
mail = Mail(app)

if app.config['SENTRY_DSN']:
    from raven.contrib.flask import Sentry

    sentry = Sentry(app, dsn=app.config['SENTRY_DSN'])

db = SQLAlchemy(metadata=metadata)
migrate = Migrate(app, db)

db.init_app(app)
oauth = OAuth(app)

twitter_oauth = oauth.remote_app(
    'twitter',
    consumer_key=app.config['TWITTER_CONSUMER_KEY'],
    consumer_secret=app.config['TWITTER_CONSUMER_SECRET'],
    base_url='https://api.twitter.com/1.1/',
    request_token_url='https://api.twitter.com/oauth/request_token',
    access_token_url='https://api.twitter.com/oauth/access_token',
    authorize_url='https://api.twitter.com/oauth/authorize'
)


@app.before_request
def before_request():
    g.t_user = None
    g.m_user = None
    g.bridge = None

    if 'twitter' in session:
        g.t_user = session['twitter']

    if 'mastodon' in session:
        g.m_user = session['mastodon']

    try:
        db.engine.execute('SELECT 1 from bridge')
    except exc.SQLAlchemyError as e:
        return "Moa is unavailable at the moment", 503

    # app.logger.info(session)


@app.route('/')
def index():
    mform = MastodonIDForm()
    settings = Settings()
    enabled = True
    found_settings = False

    if 'twitter' in session and 'mastodon' in session:
        # look up settings
        bridge = db.session.query(Bridge).filter_by(
            mastodon_user=session['mastodon']['username'],
            twitter_handle=session['twitter']['screen_name'],
        ).first()

        if bridge:
            found_settings = True
            settings = bridge.settings
            enabled = bridge.enabled
            g.bridge = bridge
            app.logger.debug(f"Existing settings found: {enabled} {settings.__dict__}")

    form = SettingsForm(obj=settings)

    return render_template('index.html.j2',
                           form=form,
                           mform=mform,
                           enabled=enabled,
                           found_settings=found_settings
                           )


@app.route('/options', methods=["POST"])
def options():
    form = SettingsForm()

    if form.validate_on_submit():

        settings = Settings()

        form.populate_obj(settings)

        bridge_found = False

        bridge = db.session.query(Bridge).filter_by(
            mastodon_user=session['mastodon']['username'],
            twitter_handle=session['twitter']['screen_name'],
        ).first()

        if bridge:
            bridge_found = True
            app.logger.debug("Existing settings found")
        else:
            bridge = Bridge()

        bridge.enabled = form.enabled.data
        bridge.settings = settings
        bridge.updated = datetime.now()
        bridge.twitter_oauth_token = session['twitter']['oauth_token']
        bridge.twitter_oauth_secret = session['twitter']['oauth_token_secret']
        bridge.twitter_handle = session['twitter']['screen_name']
        bridge.mastodon_access_code = session['mastodon']['access_code']
        bridge.mastodon_user = session['mastodon']['username']
        bridge.mastodon_host = get_or_create_host(session['mastodon']['host'])

        if not bridge.mastodon_host:
            flash(f"There was a problem connecting to {session['mastodon']['host']}")
            return redirect(url_for('index'))

        # get twitter ID
        twitter_api = twitter.Api(
            consumer_key=app.config['TWITTER_CONSUMER_KEY'],
            consumer_secret=app.config['TWITTER_CONSUMER_SECRET'],
            access_token_key=session['twitter']['oauth_token'],
            access_token_secret=session['twitter']['oauth_token_secret'],
            tweet_mode='extended'  # Allow tweets longer than 140 raw characters
        )

        if bridge.twitter_last_id == 0:
            tl = twitter_api.GetUserTimeline()
            if len(tl) > 0:
                bridge.twitter_last_id = tl[0].id
            else:
                bridge.twitter_last_id = 0

        if bridge.mastodon_last_id == 0:

            # get mastodon ID
            api = mastodon_api(session['mastodon']['host'],
                               access_code=session['mastodon']['access_code'])

            bridge.mastodon_account_id = api.account_verify_credentials()["id"]

            try:
                statuses = api.account_statuses(bridge.mastodon_account_id)
                if len(statuses) > 0:
                    bridge.mastodon_last_id = statuses[0]["id"]
                else:
                    bridge.mastodon_last_id = 0

            except MastodonAPIError:
                bridge.mastodon_last_id = 0

        app.logger.debug("Saving new settings")

        flash("Settings Saved.")
        db.session.commit()
    else:
        for e in form.errors.items():
            flash(e[1][0])
        return redirect(url_for('index'))

    return redirect(url_for('index'))


@app.route('/delete', methods=["POST"])
def delete():
    if 'twitter' in session and 'mastodon' in session:
        # look up settings
        bridge = db.session.query(Bridge).filter_by(
            mastodon_user=session['mastodon']['username'],
            twitter_handle=session['twitter']['screen_name'],
        ).first()

        if bridge:
            app.logger.info(
                f"Deleting settings for {session['mastodon']['username']} {session['twitter']['screen_name']}")
            db.session.delete(bridge)
            db.session.commit()

    return redirect(url_for('logout'))


# Twitter
#


@app.route('/twitter_login')
def twitter_login():
    callback_url = url_for(
            'twitter_oauthorized',
            _external=True,
            next=request.args.get('next')
    )

    app.logger.debug(callback_url)

    return twitter_oauth.authorize(callback=callback_url)


@app.route('/twitter_oauthorized')
def twitter_oauthorized():
    try:
        resp = twitter_oauth.authorized_response()
    except OAuthException:
        resp = None

    if resp is None:
        flash('ERROR: You denied the request to sign in or have cookies disabled.')

    elif blacklisted(resp['screen_name'], app.config.get('TWITTER_BLACKLIST', [])):
        flash('ERROR: Access Denied.')

        if app.config.get('MAIL_SERVER', None):
            body = render_template('access_denied.txt.j2', user=f"https://twitter.com/{resp['screen_name']}")
            msg = Message(subject="moa access denied",
                          body=body,
                          recipients=[app.config.get('MAIL_TO', None)])

            try:
                mail.send(msg)

            except Exception as e:
                app.logger.error(e)

    else:
        session['twitter'] = resp

    return redirect(url_for('index'))


#
# Mastodon
#


def get_or_create_host(hostname):
    mastodonhost = db.session.query(MastodonHost).filter_by(hostname=hostname).first()

    if not mastodonhost:

        try:
            client_id, client_secret = Mastodon.create_app(
                "Moa",
                scopes=["read", "write"],
                api_base_url=f"https://{hostname}",
                website="https://moa.party/",
                redirect_uris=url_for("mastodon_oauthorized", _external=True)
            )

            app.logger.info(f"New host created for {hostname}")

            mastodonhost = MastodonHost(hostname=hostname,
                                        client_id=client_id,
                                        client_secret=client_secret)
            db.session.add(mastodonhost)
            db.session.commit()
        except MastodonNetworkError as e:
            app.logger.error(e)
            return None

    app.logger.debug(f"Using Mastodon Host: {mastodonhost.hostname}")

    return mastodonhost


def mastodon_api(hostname, access_code=None):
    mastodonhost = get_or_create_host(hostname)

    if mastodonhost:
        api = Mastodon(
            client_id=mastodonhost.client_id,
            client_secret=mastodonhost.client_secret,
            api_base_url=f"https://{mastodonhost.hostname}",
            access_token=access_code,
            debug_requests=False
        )

        return api
    return None


@app.route('/mastodon_login', methods=['POST'])
def mastodon_login():
    form = MastodonIDForm()
    if form.validate_on_submit():

        user_id = form.mastodon_id.data

        if "@" not in user_id:
            flash('Invalid Mastodon ID')
            return redirect(url_for('index'))

        if user_id[0] == '@':
            user_id = user_id[1:]

        username, host = user_id.split('@')

        session['mastodon_host'] = host

        api = mastodon_api(host)

        if api:
            return redirect(
                api.auth_request_url(
                    scopes=['read', 'write'],
                    redirect_uris=url_for("mastodon_oauthorized", _external=True)
                )
            )
        else:
            flash(f"There was a problem connecting to the mastodon server.")
    else:
        flash("Invalid Mastodon ID")

    return redirect(url_for('index'))


@app.route('/mastodon_oauthorized')
def mastodon_oauthorized():
    authorization_code = request.args.get('code')

    if authorization_code is None:
        flash('You denied the request to sign in to Mastodon.')
    else:

        host = session.get('mastodon_host', None)

        app.logger.info(f"Authorization code {authorization_code} for {host}")

        if not host:
            flash('There was an error. Please ensure you allow this site to use cookies.')
            return redirect(url_for('index'))

        session.pop('mastodon_host', None)

        api = mastodon_api(host)

        try:
            access_code = api.log_in(
                    code=authorization_code,
                    scopes=["read", "write"],
                    redirect_uri=url_for("mastodon_oauthorized", _external=True)
            )
        except MastodonIllegalArgumentError as e:

            flash(f"There was a problem connecting to the mastodon server. The error was {e}")
            return redirect(url_for('index'))

        # app.logger.info(f"Access code {access_code}")

        api.access_code = access_code

        session['mastodon'] = {
            'host': host,
            'access_code': access_code,
            'username': api.account_verify_credentials()["username"]
        }

        bridge = db.session.query(Bridge).filter_by(
            mastodon_user=session['mastodon']['username'],
            twitter_handle=session['twitter']['screen_name'],
        ).first()

        if bridge:
            app.logger.debug("Existing settings found")
        else:
            bridge = Bridge()

            bridge.enabled = True
            bridge.settings = Settings()
            bridge.twitter_oauth_token = session['twitter']['oauth_token']
            bridge.twitter_oauth_secret = session['twitter']['oauth_token_secret']
            bridge.twitter_handle = session['twitter']['screen_name']
            bridge.mastodon_access_code = session['mastodon']['access_code']
            bridge.mastodon_user = session['mastodon']['username']
            bridge.mastodon_host = get_or_create_host(session['mastodon']['host'])
            db.session.add(bridge)
            db.session.commit()

            if app.config.get('MAIL_SERVER', None):
                body = render_template('new_user_email.txt.j2', bridge=bridge)
                msg = Message(subject="New moa.party user",
                              body=body,
                              recipients=[app.config.get('MAIL_TO', None)])

                try:
                    mail.send(msg)

                except Exception as e:
                    app.logger.error(e)

    return redirect(url_for('index'))


@app.route('/instagram_activate', methods=["POST"])
def instagram_activate():

    client_id = app.config['INSTAGRAM_CLIENT_ID']
    client_secret = app.config['INSTAGRAM_SECRET']
    redirect_uri = url_for('instagram_oauthorized', _external=True)
    # app.logger.info(redirect_uri)

    scope = ["basic"]
    api = InstagramAPI(client_id=client_id, client_secret=client_secret, redirect_uri=redirect_uri)
    redirect_uri = api.get_authorize_login_url(scope = scope)

    return redirect(redirect_uri)


@app.route('/instagram_oauthorized')
def instagram_oauthorized():

    code = request.args.get('code', None)

    if 'twitter' in session and 'mastodon' in session and code:

        client_id = app.config['INSTAGRAM_CLIENT_ID']
        client_secret = app.config['INSTAGRAM_SECRET']
        redirect_uri = url_for('instagram_oauthorized', _external=True)
        api = InstagramAPI(client_id=client_id, client_secret=client_secret, redirect_uri=redirect_uri)
        access_token = api.exchange_code_for_access_token(code)

        # look up settings
        bridge = db.session.query(Bridge).filter_by(
            mastodon_user=session['mastodon']['username'],
            twitter_handle=session['twitter']['screen_name'],
        ).first()

        bridge.instagram_access_code = access_token[0]

        data = access_token[1]
        bridge.instagram_account_id = data['id']
        bridge.instagram_handle = data['username']

        user_api = InstagramAPI(access_token=bridge.instagram_access_code, client_secret=client_secret)

        latest_media, _ = user_api.user_recent_media(user_id=bridge.instagram_account_id, count=1)

        if len(latest_media) > 0:
            bridge.instagram_last_id = datetime_to_timestamp(latest_media[0].created_time)
        else:
            bridge.instagram_last_id = 0

        db.session.commit()

    else:
        flash("Instagram authorization failed")

    return redirect(url_for('index'))


@app.route('/logout')
def logout():
    session.pop('twitter', None)
    session.pop('mastodon', None)
    return redirect(url_for('index'))


@app.route('/stats')
def stats():
    hours = request.args.get('hours', 24)

    return render_template('stats.html.j2',
                           hours=hours)


def timespan(hours):
    t = hours
    tw = 'hour'

    if hours % 24 == 0:
        t = hours // 24
        tw = 'days'

        if t == 1:
            tw = 'day'

    if hours % (24 * 7) == 0:
        t = hours // (24 * 7)
        tw = 'weeks'

    return f'{t} {tw}'


@app.route('/stats/times.svg')
def time_graph():
    hours = int(request.args.get('hours', 24))

    since = datetime.now() - timedelta(hours=hours)
    stats_query = db.session.query(WorkerStat).filter(WorkerStat.created > since).with_entities(WorkerStat.created,
                                                                                                WorkerStat.time,
                                                                                                WorkerStat.worker)

    df = pd.read_sql(stats_query.statement, stats_query.session.bind)

    dfs = {}
    rs = {}
    l_1 = 0
    times = {}
    main_times = pd.DataFrame({'A' : []})

    chart = pygal.Line(title=f"Worker run time (s) ({timespan(hours)})",
                       stroke_style={'width': 2},
                       legend_at_bottom=True)

    i = 1

    while i <= app.config['WORKER_JOBS']:
        dfs[i] = df[df['worker'] == i]

        dfs[i].set_index(['created'], inplace=True)
        dfs[i].groupby(level=0).mean()
        rs[i] = dfs[i].resample('h').mean()
        rs[i] = rs[i].fillna(0)
        times[i] = rs[i]['time'].tolist()

        if i == 1:
            l_1 = len(times[i])

        c_l = len(times[i])
        diff = l_1 - c_l

        if diff > 0:
            new_data = [0] * diff
            times[i] = new_data + times[i]

        chart.add(f"{i}", times[i], show_dots=False)
        i = i + 1

    return chart.render_response()


@app.route('/stats/counts.svg')
def count_graph():
    hours = int(request.args.get('hours', 24))
    since = datetime.now() - timedelta(hours=hours)

    stats_query = db.session.query(WorkerStat).filter(WorkerStat.created > since).with_entities(WorkerStat.created,
                                                                                                WorkerStat.toots,
                                                                                                WorkerStat.tweets,
                                                                                                WorkerStat.instas)

    df = pd.read_sql(stats_query.statement, stats_query.session.bind)
    df.set_index(['created'], inplace=True)

    df.groupby(level=0).sum()
    r = df.resample('h').sum()
    r = r.fillna(0)

    toots = r['toots'].tolist()
    tweets = r['tweets'].tolist()
    instas = r['instas'].tolist()

    chart = pygal.StackedBar(title=f"# of Incoming Messages ({timespan(hours)})",
                             human_readable=True,
                             legend_at_bottom=True)
    chart.add('Toots', toots)
    chart.add('Tweets', tweets)
    chart.add('Instas', instas)

    return chart.render_response()


@app.route('/stats/percent.svg')
def percent_graph():
    hours = int(request.args.get('hours', 24))
    since = datetime.now() - timedelta(hours=hours)

    stats_query = db.session.query(WorkerStat).filter(WorkerStat.created > since).with_entities(WorkerStat.created,
                                                                                                WorkerStat.toots,
                                                                                                WorkerStat.tweets,
                                                                                                WorkerStat.instas)

    df = pd.read_sql(stats_query.statement, stats_query.session.bind)
    df.set_index(['created'], inplace=True)

    df.groupby(level=0).sum()
    r = df.resample('h').sum()
    r = r.fillna(0)

    r['total'] = r['toots'] + r['tweets'] + r['instas']
    r['tweets_p'] = r['tweets'] / r['total']
    r['toots_p'] = r['toots'] / r['total']
    r['instas_p'] = r['instas'] / r['total']

    toots_p = r['toots_p'].tolist()
    tweets_p = r['tweets_p'].tolist()
    instas_p = r['instas_p'].tolist()

    chart = pygal.StackedBar(title=f"Ratio of Incoming Messages ({timespan(hours)})",
                             human_readable=True,
                             legend_at_bottom=True)
    chart.add('Tweets', tweets_p)
    chart.add('Toots', toots_p)
    chart.add('Instas', instas_p)

    return chart.render_response()


@app.route('/stats/users.svg')
def user_graph():
    hours = int(request.args.get('hours', 24))
    since = datetime.now() - timedelta(hours=hours)

    stats_query = db.session.query(Bridge).filter(Bridge.created > since).filter(Bridge.enabled == 1).with_entities(
            Bridge.created)

    base_count_query = db.session.query(func.count(Bridge.id)).scalar()

    df = pd.read_sql(stats_query.statement, stats_query.session.bind)
    df.set_index(['created'], inplace=True)
    df['count'] = 1

    # app.logger.info(df)

    # df.groupby(level=0).sum()

    r = df.resample('d').sum()
    r = r.fillna(0)
    r['cum_sum'] = r['count'].cumsum() + base_count_query

    # app.logger.info(r)

    users = r['cum_sum'].tolist()
    # app.logger.info(users)

    chart = pygal.Line(title=f"# of Users ({timespan(hours)})",
                       stroke_style={'width': 5},
                       show_legend=False)
    chart.add('Users', users, fill=True, show_dots=False)

    return chart.render_response()


@app.route('/privacy')
def privacy():
    return render_template('privacy.html.j2')


@app.errorhandler(404)
def page_not_found(e):
    return render_template('404.html'), 404


if __name__ == '__main__':

    app.run()
