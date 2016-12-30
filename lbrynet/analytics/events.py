import logging

from lbrynet.core import utils
from lbrynet.conf import LBRYUM_WALLET

log = logging.getLogger(__name__)


def get_sd_hash(stream_info):
    if not stream_info:
        return None
    try:
        return stream_info['sources']['lbry_sd_hash']
    except (KeyError, TypeError, ValueError):
        log.debug('Failed to get sd_hash from %s', stream_info, exc_info=True)
        return None


class Events(object):
    def __init__(self, context, lbry_id, session_id):
        self.context = context
        self.lbry_id = lbry_id
        self.session_id = session_id

    def update_context(self, context):
        self.context = context

    def server_startup(self):
        return self._event('Server Startup')

    def server_startup_success(self):
        return self._event('Server Startup Success')

    def server_startup_error(self, message):
        return self._event('Server Startup Error', {
            'message': message,
        })

    def heartbeat(self):
        return self._event('Heartbeat')

    def download_started(self, *args, **kwargs):
        properties = download_properties(*args, **kwargs)
        return self._event('Download Started', properties)

    def download_errored(self, *args, **kwargs):
        properties = download_properties(*args, **kwargs)
        return self._event('Download Errored', properties)

    def download_finished(self, *args, **kwargs):
        properties = download_properties(*args, **kwargs)
        return self._event('Download Finished', properties)

    def error(self, message, sd_hash=None):
        properties = {
            'message': message,
            'stream_info': sd_hash
        }
        return self._event('Error', properties)

    def metric_observed(self, metric_name, value):
        properties = {
            'value': value,
        }
        return self._event(metric_name, properties)

    def _event(self, event, event_properties=None):
        return {
            'userId': 'lbry',
            'event': event,
            'properties': self._properties(event_properties),
            'context': self.context,
            'timestamp': utils.isonow()
        }

    def _properties(self, event_properties=None):
        event_properties = event_properties or {}
        properties = {
            'lbry_id': self.lbry_id,
            'session_id': self.session_id,
        }
        properties.update(event_properties)
        return properties


def make_context(platform, wallet):
    return {
        'app': {
            'name': 'lbrynet',
            'version': platform['lbrynet_version'],
            'ui_version': platform['ui_version'],
            'python_version': platform['python_version'],
            'build': platform['build'],
            'wallet': {
                'name': wallet,
                'version': platform['lbryum_version'] if wallet == LBRYUM_WALLET else None
            },
        },
        # TODO: expand os info to give linux/osx specific info
        'os': {
            'name': platform['os_system'],
            'version': platform['os_release']
        },
        'library': {
            'name': 'lbrynet-analytics',
            'version': '1.0.0'
        },
    }


def download_properties(id_, name, stream_info=None):
    return {
        'download_id': id_,
        'name': name,
        'stream_info': get_sd_hash(stream_info)
    }
