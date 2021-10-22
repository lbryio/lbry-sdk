import asyncio
import collections
import logging
import typing
import aiohttp
from lbry import utils
from lbry.conf import Config
from lbry.extras import system_info

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
DISK_SPACE = 'Disk Space'
CLAIM_ACTION = 'Claim Action'  # publish/create/update/abandon
NEW_CHANNEL = 'New Channel'
CREDITS_SENT = 'Credits Sent'
UPNP_SETUP = "UPnP Setup"

BLOB_BYTES_UPLOADED = 'Blob Bytes Uploaded'


TIME_TO_FIRST_BYTES = "Time To First Bytes"


log = logging.getLogger(__name__)


def _event_properties(installation_id: str, session_id: str,
                      event_properties: typing.Optional[typing.Dict]) -> typing.Dict:
    properties = {
        'lbry_id': installation_id,
        'session_id': session_id,
    }
    properties.update(event_properties or {})
    return properties


def _download_properties(conf: Config, external_ip: str, resolve_duration: float,
                         total_duration: typing.Optional[float], download_id: str, name: str,
                         outpoint: str, active_peer_count: typing.Optional[int],
                         tried_peers_count: typing.Optional[int], connection_failures_count: typing.Optional[int],
                         added_fixed_peers: bool, fixed_peer_delay: float, sd_hash: str,
                         sd_download_duration: typing.Optional[float] = None,
                         head_blob_hash: typing.Optional[str] = None,
                         head_blob_length: typing.Optional[int] = None,
                         head_blob_download_duration: typing.Optional[float] = None,
                         error: typing.Optional[str] = None, error_msg: typing.Optional[str] = None,
                         wallet_server: typing.Optional[str] = None) -> typing.Dict:
    return {
        "external_ip": external_ip,
        "download_id": download_id,
        "total_duration": round(total_duration, 4),
        "resolve_duration": None if not resolve_duration else round(resolve_duration, 4),
        "error": error,
        "error_message": error_msg,
        'name': name,
        "outpoint": outpoint,

        "node_rpc_timeout": conf.node_rpc_timeout,
        "peer_connect_timeout": conf.peer_connect_timeout,
        "blob_download_timeout": conf.blob_download_timeout,
        "use_fixed_peers": len(conf.fixed_peers) > 0,
        "fixed_peer_delay": fixed_peer_delay,
        "added_fixed_peers": added_fixed_peers,
        "active_peer_count": active_peer_count,
        "tried_peers_count": tried_peers_count,

        "sd_blob_hash": sd_hash,
        "sd_blob_duration": None if not sd_download_duration else round(sd_download_duration, 4),

        "head_blob_hash": head_blob_hash,
        "head_blob_length": head_blob_length,
        "head_blob_duration": None if not head_blob_download_duration else round(head_blob_download_duration, 4),

        "connection_failures_count": connection_failures_count,
        "wallet_server": wallet_server
    }


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
        self.conf = conf
        self.cookies = {}
        self.url = ANALYTICS_ENDPOINT
        self._write_key = utils.deobfuscate(ANALYTICS_TOKEN)
        self._tracked_data = collections.defaultdict(list)
        self.context = _make_context(system_info.get_platform())
        self.installation_id = installation_id
        self.session_id = session_id
        self.task: typing.Optional[asyncio.Task] = None
        self.external_ip: typing.Optional[str] = None

    @property
    def enabled(self):
        return self.conf.share_usage_data

    @property
    def is_started(self):
        return self.task is not None

    async def start(self):
        if self.task is None:
            self.task = asyncio.create_task(self.run())

    async def run(self):
        while True:
            if self.enabled:
                self.external_ip, _ = await utils.get_external_ip(self.conf.lbryum_servers)
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
            log.debug('Encountered an exception while POSTing to %s: ', self.url + '/track', exc_info=e)

    async def track(self, event: typing.Dict):
        """Send a single tracking event"""
        if self.enabled:
            log.debug('Sending track event: %s', event)
            await self._post(event)

    async def send_upnp_setup_success_fail(self, success, status):
        await self.track(
            self._event(UPNP_SETUP, {
                'success': success,
                'status': status,
            })
        )

    async def send_disk_space_used(self, storage_used, storage_limit, is_from_network_quota):
        await self.track(
            self._event(DISK_SPACE, {
                'used': storage_used,
                'limit': storage_limit,
                'from_network_quota': is_from_network_quota
            })
        )

    async def send_server_startup(self):
        await self.track(self._event(SERVER_STARTUP))

    async def send_server_startup_success(self):
        await self.track(self._event(SERVER_STARTUP_SUCCESS))

    async def send_server_startup_error(self, message):
        await self.track(self._event(SERVER_STARTUP_ERROR, {'message': message}))

    async def send_time_to_first_bytes(self, resolve_duration: typing.Optional[float],
                                       total_duration: typing.Optional[float], download_id: str,
                                       name: str, outpoint: typing.Optional[str],
                                       found_peers_count: typing.Optional[int],
                                       tried_peers_count: typing.Optional[int],
                                       connection_failures_count: typing.Optional[int],
                                       added_fixed_peers: bool,
                                       fixed_peers_delay: float, sd_hash: str,
                                       sd_download_duration: typing.Optional[float] = None,
                                       head_blob_hash: typing.Optional[str] = None,
                                       head_blob_length: typing.Optional[int] = None,
                                       head_blob_duration: typing.Optional[int] = None,
                                       error: typing.Optional[str] = None,
                                       error_msg: typing.Optional[str] = None,
                                       wallet_server: typing.Optional[str] = None):
        await self.track(self._event(TIME_TO_FIRST_BYTES, _download_properties(
            self.conf, self.external_ip, resolve_duration, total_duration, download_id, name, outpoint,
            found_peers_count, tried_peers_count, connection_failures_count, added_fixed_peers, fixed_peers_delay,
            sd_hash, sd_download_duration, head_blob_hash, head_blob_length, head_blob_duration, error, error_msg,
            wallet_server
        )))

    async def send_download_finished(self, download_id, name, sd_hash):
        await self.track(
            self._event(
                DOWNLOAD_FINISHED, {
                    'download_id': download_id,
                    'name': name,
                    'stream_info': sd_hash
                }
            )
        )

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
