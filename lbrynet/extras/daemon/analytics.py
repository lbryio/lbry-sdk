import asyncio
import collections
import logging

import aiohttp

from lbrynet import utils
from lbrynet.conf import Config, ANALYTICS_ENDPOINT, ANALYTICS_TOKEN
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

    def __init__(self, conf: Config, installation_id: str, session_id: str):
        self.cookies = {}
        self.url = ANALYTICS_ENDPOINT
        self._write_key = utils.deobfuscate(ANALYTICS_TOKEN)
        self._enabled = conf.share_usage_data
        self._tracked_data = collections.defaultdict(list)
        self.context = self._make_context(system_info.get_platform(), 'torba')
        self.installation_id = installation_id
        self.session_id = session_id
        self.task: asyncio.Task = None

    @property
    def is_started(self):
        return self.task is not None

    def start(self):
        if self._enabled and self.task is None:
            self.task = asyncio.create_task(self.run())
            log.info("Start")

    async def run(self):
        while True:
            await self._send_heartbeat()
            await asyncio.sleep(1800)

    def stop(self):
        if self.task is not None and not self.task.done():
            self.task.cancel()

    async def _post(self, endpoint, data):
        # there is an issue with a timing condition with keep-alive
        # that is best explained here: https://github.com/mikem23/keepalive-race
        #
        #   If you make a request, wait just the right amount of time,
        #   then make another request, the requests module may opt to
        #   reuse the connection, but by the time the server gets it the
        #   timeout will have expired.
        #
        # by forcing the connection to close, we will disable the keep-alive.

        assert endpoint[0] == '/'
        request_kwargs = {
            'method': 'POST',
            'url': self.url + endpoint,
            'headers': {'Connection': 'Close'},
            'auth': aiohttp.BasicAuth(self._write_key, ''),
            'json': data,
            'cookies': self.cookies
        }
        try:
            async with aiohttp.request(**request_kwargs) as response:
                self.cookies.update(response.cookies)
        except Exception as e:
            log.exception('Encountered an exception while POSTing to %s: ', self.url + endpoint, exc_info=e)

    async def track(self, event):
        """Send a single tracking event"""
        if self._enabled:
            log.debug('Sending track event: %s', event)
            await self._post('/track', event)

    async def send_new_download_start(self, download_id, name, claim_dict):
        await self._send_new_download_stats("start", download_id, name, claim_dict)

    async def send_new_download_success(self, download_id, name, claim_dict):
        await self._send_new_download_stats("success", download_id, name, claim_dict)

    async def send_new_download_fail(self, download_id, name, claim_dict, e):
        await self._send_new_download_stats("failure", download_id, name, claim_dict, {
            'name': type(e).__name__ if hasattr(type(e), "__name__") else str(type(e)),
            'message': str(e),
        })

    async def _send_new_download_stats(self, action, download_id, name, claim_dict, e=None):
        await self.track({
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

    async def send_upnp_setup_success_fail(self, success, status):
        await self.track(
            self._event(UPNP_SETUP, {
                'success': success,
                'status': status,
            })
        )

    async def send_server_startup(self):
        await self.track(self._event(SERVER_STARTUP))

    async def send_server_startup_success(self):
        await self.track(self._event(SERVER_STARTUP_SUCCESS))

    async def send_server_startup_error(self, message):
        await self.track(self._event(SERVER_STARTUP_ERROR, {'message': message}))

    async def send_download_started(self, id_, name, claim_dict=None):
        await self.track(
            self._event(DOWNLOAD_STARTED, self._download_properties(id_, name, claim_dict))
        )

    async def send_download_errored(self, err, id_, name, claim_dict, report):
        download_error_properties = self._download_error_properties(err, id_, name, claim_dict,
                                                                    report)
        await self.track(self._event(DOWNLOAD_ERRORED, download_error_properties))

    async def send_download_finished(self, id_, name, report, claim_dict=None):
        download_properties = self._download_properties(id_, name, claim_dict, report)
        await self.track(self._event(DOWNLOAD_FINISHED, download_properties))

    async def send_claim_action(self, action):
        await self.track(self._event(CLAIM_ACTION, {'action': action}))

    async def send_new_channel(self):
        await self.track(self._event(NEW_CHANNEL))

    async def send_credits_sent(self):
        await self.track(self._event(CREDITS_SENT))

    async def _send_heartbeat(self):
        await self.track(self._event(HEARTBEAT))

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
