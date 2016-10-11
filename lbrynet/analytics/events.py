import logging

from lbrynet.core import utils


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

    def heartbeat(self):
        return self._event('Heartbeat')

    def download_started(self, name, stream_info=None):
        properties = {
            'name': name,
            'stream_info': get_sd_hash(stream_info)
        }
        return self._event('Download Started', properties)

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


def make_context(platform, wallet, is_dev=False):
    # TODO: distinguish between developer and release instances
    return {
        'is_dev': is_dev,
        'app': {
            'name': 'lbrynet',
            'version': platform['lbrynet_version'],
            'ui_version': platform['ui_version'],
            'python_version': platform['python_version'],
            'wallet': {
                'name': wallet,
                # TODO: add in version info for lbrycrdd
                'version': platform['lbryum_version'] if wallet == 'lbryum' else None
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
