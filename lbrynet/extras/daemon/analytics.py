import asyncio
import typing
import collections
import logging

import asyncio
import aiohttp

from lbrynet import conf, utils
from lbrynet.extras import system_info

# Things We Track
SERVER_STARTUP = 'Server Startup'
SERVER_STARTUP_SUCCESS = 'Server Startup Success'
SERVER_STARTUP_ERROR = 'Server Startup Error'
DOWNLOAD_STARTED = 'Download Started'
DOWNLOAD_ERRORED = 'Download Errored'
DOWNLOAD_FINISHED = 'Download Finished'
HEARTBEAT = 'Heartbeat'
CLAIM_ACTION = 'Claim Action'  # publish/create/update/abandon
NEW_CHANNEL = 'New Channel'
CREDITS_SENT = 'Credits Sent'
NEW_DOWNLOAD_STAT = 'Download'
UPNP_SETUP = "UPnP Setup"

BLOB_BYTES_UPLOADED = 'Blob Bytes Uploaded'

log = logging.getLogger(__name__)


class Manager:
    def __init__(self, loop: asyncio.BaseEventLoop):
        self.loop = loop
        self.analytics_api = Api(loop)
        self._tracked_data = collections.defaultdict(list)
        self.looping_tasks = {}
        self.context = self._make_context(system_info.get_platform(), conf.settings['wallet'])
        self.installation_id = conf.settings.installation_id
        self.session_id = conf.settings.get_session_id()
        self._update_tracked_metrics_task: asyncio.Task = None

    # Things We Track
    def send_new_download_start(self, download_id, name, claim_dict):
        return self._send_new_download_stats("start", download_id, name, claim_dict)

    def send_new_download_success(self, download_id, name, claim_dict):
        return self._send_new_download_stats("success", download_id, name, claim_dict)

    def send_new_download_fail(self, download_id, name, claim_dict, e):
        return self._send_new_download_stats("failure", download_id, name, claim_dict, {
            'name': type(e).__name__ if hasattr(type(e), "__name__") else str(type(e)),
            'message': str(e),
        })

    def _send_new_download_stats(self, action, download_id, name, claim_dict, e=None):
        return self.analytics_api.track({
            'userId': 'lbry',  # required, see https://segment.com/docs/sources/server/http/#track
            'event': NEW_DOWNLOAD_STAT,
            'properties': self._event_properties({
                'download_id': download_id,
                'name': name,
                'sd_hash': None if not claim_dict else claim_dict.source_hash.decode(),
                'action': action,
                'error': e,
            }),
            'context': self.context,
            'timestamp': utils.isonow(),
        })

    def send_upnp_setup_success_fail(self, success, status):
        return self.analytics_api.track(
            self._event(UPNP_SETUP, {
                'success': success,
                'status': status,
            })
        )

    def send_server_startup(self):
        return self.analytics_api.track(self._event(SERVER_STARTUP))

    def send_server_startup_success(self):
        return self.analytics_api.track(self._event(SERVER_STARTUP_SUCCESS))

    def send_server_startup_error(self, message):
        return self.analytics_api.track(self._event(SERVER_STARTUP_ERROR, {'message': message}))

    def send_download_started(self, id_, name, claim_dict=None):
        return self.analytics_api.track(
            self._event(DOWNLOAD_STARTED, self._download_properties(id_, name, claim_dict))
        )

    def send_download_errored(self, err, id_, name, claim_dict, report):
        download_error_properties = self._download_error_properties(err, id_, name, claim_dict,
                                                                    report)
        return self.analytics_api.track(self._event(DOWNLOAD_ERRORED, download_error_properties))

    def send_download_finished(self, id_, name, report, claim_dict=None):
        download_properties = self._download_properties(id_, name, claim_dict, report)
        return self.analytics_api.track(self._event(DOWNLOAD_FINISHED, download_properties))

    def send_claim_action(self, action):
        return self.analytics_api.track(self._event(CLAIM_ACTION, {'action': action}))

    def send_new_channel(self):
        return self.analytics_api.track(self._event(NEW_CHANNEL))

    def send_credits_sent(self):
        return self.analytics_api.track(self._event(CREDITS_SENT))

    def _send_heartbeat(self):
        return self.analytics_api.track(self._event(HEARTBEAT))

    # Setup / Shutdown

    def start(self):
        async def update_tracked_metrics():
            try:
                while True:
                    await self._send_heartbeat()
                    await asyncio.sleep(1800, loop=self.loop)
            except asyncio.CancelledError:
                return

        self._update_tracked_metrics_task = self.loop.create_task(update_tracked_metrics())

    def shutdown(self):
        if self._update_tracked_metrics_task and not (self._update_tracked_metrics_task.done() or
        self._update_tracked_metrics_task.cancelled()):
            self._update_tracked_metrics_task.cancel()
        self._update_tracked_metrics_task = None

    def _event(self, event, event_properties=None):
        return {
            'userId': 'lbry',
            'event': event,
            'properties': self._event_properties(event_properties),
            'context': self.context,
            'timestamp': utils.isonow()
        }

    def _metric_event(self, metric_name, value):
        return self._event(metric_name, {'value': value})

    def _event_properties(self, event_properties=None):
        properties = {
            'lbry_id': self.installation_id,
            'session_id': self.session_id,
        }
        properties.update(event_properties or {})
        return properties

    @staticmethod
    def _download_properties(id_, name, claim_dict=None, report=None):
        sd_hash = None if not claim_dict else claim_dict.source_hash.decode()
        p = {
            'download_id': id_,
            'name': name,
            'stream_info': sd_hash
        }
        if report:
            p['report'] = report
        return p

    @staticmethod
    def _download_error_properties(error, id_, name, claim_dict, report):
        def error_name(err):
            if not hasattr(type(err), "__name__"):
                return str(type(err))
            return type(err).__name__
        return {
            'download_id': id_,
            'name': name,
            'stream_info': claim_dict.source_hash.decode(),
            'error': error_name(error),
            'reason': str(error),
            'report': report
        }

    @staticmethod
    def _make_context(platform, wallet):
        # see https://segment.com/docs/spec/common/#context
        # they say they'll ignore fields outside the spec, but evidently they don't
        context = {
            'app': {
                'version': platform['lbrynet_version'],
                'build': platform['build'],
            },
            # TODO: expand os info to give linux/osx specific info
            'os': {
                'name': platform['os_system'],
                'version': platform['os_release']
            },
        }
        if 'desktop' in platform and 'distro' in platform:
            context['os']['desktop'] = platform['desktop']
            context['os']['distro'] = platform['distro']
        return context


class Api:
    def __init__(self, loop: asyncio.BaseEventLoop):
        self.loop = loop
        self.cookies = {}
        self.url = conf.settings['ANALYTICS_ENDPOINT']
        self._write_key = utils.deobfuscate(conf.settings['ANALYTICS_TOKEN'])

    @property
    def enabled(self):
        return conf.settings['share_usage_data']

    async def _post(self, endpoint, data):
        assert endpoint[0] == '/'
        try:
            async with aiohttp.request('post', self.url + endpoint, headers={'Connection': 'Close'},
                                       auth=aiohttp.BasicAuth(self._write_key, ''), json=data,
                                       cookies=self.cookies) as response:
                self.cookies.update(response.cookies)
        except Exception as e:
            log.warning('Encountered an exception while POSTing to %s: ', self.url + endpoint, exc_info=e)

    def track(self, event) -> asyncio.Future:
        """Send a single tracking event"""
        if self.enabled:
            log.info('Sending track event: %s', event)
            return asyncio.ensure_future(self._post('/track', event), loop=self.loop)
        fut = asyncio.Future(loop=self.loop)
        fut.set_result(None)
        return fut
