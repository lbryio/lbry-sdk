import asyncio
import collections
import logging
import aiohttp
import typing
import binascii
from lbrynet import utils
from lbrynet.conf import Config
from lbrynet.extras import system_info

ANALYTICS_ENDPOINT = 'https://api.segment.io/v1'
ANALYTICS_TOKEN = 'Ax5LZzR1o3q3Z3WjATASDwR5rKyHH0qOIRIbLmMXn2H='

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
UPNP_SETUP = "UPnP Setup"

BLOB_BYTES_UPLOADED = 'Blob Bytes Uploaded'

log = logging.getLogger(__name__)


def _event_properties(installation_id: str, session_id: str,
                      event_properties: typing.Optional[typing.Dict]) -> typing.Dict:
    properties = {
        'lbry_id': installation_id,
        'session_id': session_id,
    }
    properties.update(event_properties or {})
    return properties


def _download_properties(download_id: str, name: str, sd_hash: str) -> typing.Dict:
    p = {
        'download_id': download_id,
        'name': name,
        'stream_info': sd_hash
    }
    return p


def _make_context(platform):
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


class AnalyticsManager:

    def __init__(self, conf: Config, installation_id: str, session_id: str):
        self.cookies = {}
        self.url = ANALYTICS_ENDPOINT
        self._write_key = utils.deobfuscate(ANALYTICS_TOKEN)
        self._enabled = conf.share_usage_data
        self._tracked_data = collections.defaultdict(list)
        self.context = _make_context(system_info.get_platform())
        self.installation_id = installation_id
        self.session_id = session_id
        self.task: asyncio.Task = None

    @property
    def is_started(self):
        return self.task is not None

    def start(self):
        if self._enabled and self.task is None:
            self.task = asyncio.create_task(self.run())

    async def run(self):
        while True:
            await self._send_heartbeat()
            await asyncio.sleep(1800)

    def stop(self):
        if self.task is not None and not self.task.done():
            self.task.cancel()

    async def _post(self, data: typing.Dict):
        request_kwargs = {
            'method': 'POST',
            'url': self.url + '/track',
            'headers': {'Connection': 'Close'},
            'auth': aiohttp.BasicAuth(self._write_key, ''),
            'json': data,
            'cookies': self.cookies
        }
        try:
            async with utils.aiohttp_request(**request_kwargs) as response:
                self.cookies.update(response.cookies)
        except Exception as e:
            log.exception('Encountered an exception while POSTing to %s: ', self.url + '/track', exc_info=e)

    async def track(self, event: typing.Dict):
        """Send a single tracking event"""
        if self._enabled:
            log.debug('Sending track event: %s', event)
            await self._post(event)

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

    async def send_download_started(self, download_id, name, sd_hash):
        await self.track(
            self._event(DOWNLOAD_STARTED, _download_properties(download_id, name, sd_hash))
        )

    async def send_download_finished(self, download_id, name, sd_hash):
        await self.track(self._event(DOWNLOAD_FINISHED, _download_properties(download_id, name, sd_hash)))

    async def send_download_errored(self, error: Exception, name: str):
        await self.track(self._event(DOWNLOAD_ERRORED, {
            'download_id': binascii.hexlify(utils.generate_id()).decode(),
            'name': name,
            'stream_info': None,
            'error': type(error).__name__,
            'reason': str(error),
            'report': None
        }))

    async def send_claim_action(self, action):
        await self.track(self._event(CLAIM_ACTION, {'action': action}))

    async def send_new_channel(self):
        await self.track(self._event(NEW_CHANNEL))

    async def send_credits_sent(self):
        await self.track(self._event(CREDITS_SENT))

    async def _send_heartbeat(self):
        await self.track(self._event(HEARTBEAT))

    def _event(self, event, properties: typing.Optional[typing.Dict] = None):
        return {
            'userId': 'lbry',
            'event': event,
            'properties': _event_properties(self.installation_id, self.session_id, properties),
            'context': self.context,
            'timestamp': utils.isonow()
        }
