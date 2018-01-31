import os
from datetime import datetime, timedelta

import pandas as pd
import pygal
import twitter
from flask import Flask, flash, g, redirect, render_template, request, session, url_for
from flask_mail import Message, Mail
from flask_oauthlib.client import OAuth
from flask_sqlalchemy import SQLAlchemy
from mastodon import Mastodon
from mastodon.Mastodon import MastodonAPIError, MastodonNetworkError
from pygal.style import LightGreenStyle
from sqlalchemy import exc

from moa.forms import MastodonIDForm, SettingsForm
from moa.models import Bridge, MastodonHost, WorkerStat, metadata
from moa.settings import Settings

app = Flask(__name__)
config = os.environ.get('MOA_CONFIG', 'config.DevelopmentConfig')
app.config.from_object(config)
mail = Mail(app)

if app.config['SENTRY_DSN']:
    from raven.contrib.flask import Sentry

    sentry = Sentry(app, dsn=app.config['SENTRY_DSN'])

db = SQLAlchemy(metadata=metadata)
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

        if not bridge_found:
            tl = twitter_api.GetUserTimeline()
            if len(tl) > 0:
                bridge.twitter_last_id = tl[0].id
            else:
                bridge.twitter_last_id = 0

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

        if not bridge_found:
            db.session.add(bridge)

            body = render_template('new_user_email.txt.j2', bridge=bridge)

            msg = Message(subject="New moa.party user",
                          body=body,
                          sender="hello@jmoore.me",
                          recipients=["hello@jmoore.me"])

            try:
                mail.send(msg)

            except Exception as e:
                app.logger.error(e)

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
    callback_url = url_for('twitter_oauthorized', next=request.args.get('next'))

    app.logger.debug(callback_url)

    return twitter_oauth.authorize(callback=callback_url)


@app.route('/twitter_oauthorized')
def twitter_oauthorized():
    resp = twitter_oauth.authorized_response()
    if resp is None:
        flash('You denied the request to sign in.')
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

            app.logger.info(f"New host created for {hostname} {client_id} {client_secret}")

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
    app.logger.info(f"Authorization code {authorization_code}")

    if authorization_code is None:
        flash('You denied the request to sign in to Mastodon.')
    else:

        host = session['mastodon_host']
        session.pop('mastodon_host', None)

        api = mastodon_api(host)

        access_code = api.log_in(
            code=authorization_code,
            scopes=["read", "write"],
            redirect_uri=url_for("mastodon_oauthorized", _external=True)
        )

        app.logger.info(f"Access code {access_code}")

        api.access_code = access_code

        session['mastodon'] = {
            'host': host,
            'access_code': access_code,
            'username': api.account_verify_credentials()["username"]
        }

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


@app.route('/stats/times.svg')
def time_graph():

    hours = request.args.get('hours', 24)

    since = datetime.now() - timedelta(hours=hours)
    stats_query = db.session.query(WorkerStat).filter(WorkerStat.created > since).with_entities(WorkerStat.created,
                                                                                                WorkerStat.time,
                                                                                                WorkerStat.avg)

    df = pd.read_sql(stats_query.statement, stats_query.session.bind)

    df.set_index(['created'], inplace=True)

    df.groupby(level=0).mean()
    r = df.resample('h').mean()
    r = r.fillna(0)

    times = r['time'].tolist()
    # avg = r['avg'].tolist()

    chart = pygal.Line(title="Worker run time (s) in the last 24 hours",
                       stroke_style={'width': 5},
                       style=LightGreenStyle,
                       show_legend=False)

    chart.add('Total time', times, fill=True, show_dots=False)
    # chart.add('Avg time', avg)

    return chart.render_response()


@app.route('/stats/counts.svg')
def count_graph():
    hours = request.args.get('hours', 24)

    since = datetime.now() - timedelta(hours=hours)
    stats_query = db.session.query(WorkerStat).filter(WorkerStat.created > since).with_entities(WorkerStat.created,
                                                                                                WorkerStat.toots,
                                                                                                WorkerStat.tweets)

    df = pd.read_sql(stats_query.statement, stats_query.session.bind)
    df.set_index(['created'], inplace=True)

    df.groupby(level=0).sum()
    r = df.resample('h').sum()
    r = r.fillna(0)

    toots = r['toots'].tolist()
    tweets = r['tweets'].tolist()

    chart = pygal.StackedBar(title="# of Incoming Messages in the last 24 hours",
                             human_readable=True,
                             style=LightGreenStyle,
                             legend_at_bottom=True)
    chart.add('Toots', toots)
    chart.add('Tweets', tweets)

    return chart.render_response()


@app.route('/stats/users.svg')
def user_graph():
    stats_query = db.session.query(Bridge).with_entities(Bridge.created)

    df = pd.read_sql(stats_query.statement, stats_query.session.bind)
    df.set_index(['created'], inplace=True)
    df['count'] = 1

    # app.logger.info(df)

    # df.groupby(level=0).sum()

    r = df.resample('d').sum()
    r = r.fillna(0)
    r['cum_sum'] = r['count'].cumsum()

    # app.logger.info(r)

    users = r['cum_sum'].tolist()
    # app.logger.info(users)

    chart = pygal.Line(title="# of Users (all time)",
                       stroke_style={'width': 5},
                       style=LightGreenStyle,
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
