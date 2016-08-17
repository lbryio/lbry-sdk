import functools
import json
import logging

from requests import auth
from requests_futures import sessions

from lbrynet import conf
from lbrynet.analytics import utils


log = logging.getLogger(__name__)


def log_response(fn):
    def _log(future):
        if future.cancelled():
            log.warning('Request was unexpectedly cancelled')
        else:
            response = future.result()
            log.debug('Response (%s): %s', response.status_code, response.content)

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        future = fn(*args, **kwargs)
        future.add_done_callback(_log)
        return future
    return wrapper


class AnalyticsApi(object):
    def __init__(self, session, url, write_key):
        self.session = session
        self.url = url
        self.write_key = write_key

    @property
    def auth(self):
        return auth.HTTPBasicAuth(self.write_key, '')

    @log_response
    def batch(self, events):
        """Send multiple events in one request.

        Each event needs to have its type specified.
        """
        data = json.dumps({
            'batch': events,
            'sentAt': utils.now(),
        })
        log.debug('sending %s events', len(events))
        log.debug('Data: %s', data)
        return self.session.post(self.url + '/batch', json=data, auth=self.auth)

    @log_response
    def track(self, event):
        """Send a single tracking event"""
        log.debug('Sending track event: %s', event)
        import base64
        return self.session.post(self.url + '/track', json=event, auth=self.auth)

    @classmethod
    def load(cls, session=None):
        """Initialize an instance using values from lbry.io."""
        if not session:
            session = sessions.FuturesSession()
        return cls(
            session,
            conf.ANALYTICS_ENDPOINT,
            utils.deobfuscate(conf.ANALYTICS_TOKEN)
        )
