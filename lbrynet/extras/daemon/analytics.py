import collections
import logging

import treq
from twisted.internet import defer, task

from lbrynet.extras.daemon import conf
from lbrynet.p2p import looping_call_manager, utils, system_info

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
    def __init__(self, analytics_api, context=None, installation_id=None, session_id=None):
        self.analytics_api = analytics_api
        self._tracked_data = collections.defaultdict(list)
        self.looping_call_manager = self._setup_looping_calls()
        self.context = context or self._make_context(
            system_info.get_platform(), conf.settings['wallet'])
        self.installation_id = installation_id or conf.settings.installation_id
        self.session_id = session_id or conf.settings.get_session_id()
        self.is_started = False

    @classmethod
    def new_instance(cls, enabled=None):
        api = Api.new_instance(enabled)
        return cls(api)

    # Things We Track
    def send_new_download_start(self, download_id, name, claim_dict):
        self._send_new_download_stats("start", download_id, name, claim_dict)

    def send_new_download_success(self, download_id, name, claim_dict):
        self._send_new_download_stats("success", download_id, name, claim_dict)

    def send_new_download_fail(self, download_id, name, claim_dict, e):
        self._send_new_download_stats("failure", download_id, name, claim_dict, {
            'name': type(e).__name__ if hasattr(type(e), "__name__") else str(type(e)),
            'message': str(e),
        })

    def _send_new_download_stats(self, action, download_id, name, claim_dict, e=None):
        self.analytics_api.track({
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
        self.analytics_api.track(
            self._event(UPNP_SETUP, {
                'success': success,
                'status': status,
            })
        )

    def send_server_startup(self):
        self.analytics_api.track(self._event(SERVER_STARTUP))

    def send_server_startup_success(self):
        self.analytics_api.track(self._event(SERVER_STARTUP_SUCCESS))

    def send_server_startup_error(self, message):
        self.analytics_api.track(self._event(SERVER_STARTUP_ERROR, {'message': message}))

    def send_download_started(self, id_, name, claim_dict=None):
        self.analytics_api.track(
            self._event(DOWNLOAD_STARTED, self._download_properties(id_, name, claim_dict))
        )

    def send_download_errored(self, err, id_, name, claim_dict, report):
        download_error_properties = self._download_error_properties(err, id_, name, claim_dict,
                                                                    report)
        self.analytics_api.track(self._event(DOWNLOAD_ERRORED, download_error_properties))

    def send_download_finished(self, id_, name, report, claim_dict=None):
        download_properties = self._download_properties(id_, name, claim_dict, report)
        self.analytics_api.track(self._event(DOWNLOAD_FINISHED, download_properties))

    def send_claim_action(self, action):
        self.analytics_api.track(self._event(CLAIM_ACTION, {'action': action}))

    def send_new_channel(self):
        self.analytics_api.track(self._event(NEW_CHANNEL))

    def send_credits_sent(self):
        self.analytics_api.track(self._event(CREDITS_SENT))

    def _send_heartbeat(self):
        self.analytics_api.track(self._event(HEARTBEAT))

    def _update_tracked_metrics(self):
        should_send, value = self.summarize_and_reset(BLOB_BYTES_UPLOADED)
        if should_send:
            self.analytics_api.track(self._metric_event(BLOB_BYTES_UPLOADED, value))

    # Setup / Shutdown

    def start(self):
        if not self.is_started:
            for name, _, interval in self._get_looping_calls():
                self.looping_call_manager.start(name, interval)
            self.is_started = True

    def shutdown(self):
        self.looping_call_manager.shutdown()

    def register_repeating_metric(self, event_name, value_generator, frequency=300):
        lcall = task.LoopingCall(self._send_repeating_metric, event_name, value_generator)
        self.looping_call_manager.register_looping_call(event_name, lcall)
        lcall.start(frequency)

    def _get_looping_calls(self):
        return [
            ('send_heartbeat', self._send_heartbeat, 60),
            ('update_tracked_metrics', self._update_tracked_metrics, 300),
        ]

    def _setup_looping_calls(self):
        call_manager = looping_call_manager.LoopingCallManager()
        for name, fn, _ in self._get_looping_calls():
            call_manager.register_looping_call(name, task.LoopingCall(fn))
        return call_manager

    def _send_repeating_metric(self, event_name, value_generator):
        result = value_generator()
        self._if_deferred(result, self._send_repeating_metric_value, event_name)

    def _send_repeating_metric_value(self, result, event_name):
        should_send, value = result
        if should_send:
            self.analytics_api.track(self._metric_event(event_name, value))

    def add_observation(self, metric, value):
        self._tracked_data[metric].append(value)

    def summarize_and_reset(self, metric, op=sum):
        """Apply `op` on the current values for `metric`.

        This operation also resets the metric.

        Returns:
            a tuple (should_send, value)
        """
        try:
            values = self._tracked_data.pop(metric)
            return True, op(values)
        except KeyError:
            return False, None

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

    @staticmethod
    def _if_deferred(maybe_deferred, callback, *args, **kwargs):
        if isinstance(maybe_deferred, defer.Deferred):
            maybe_deferred.addCallback(callback, *args, **kwargs)
        else:
            callback(maybe_deferred, *args, **kwargs)


class Api:
    def __init__(self, cookies, url, write_key, enabled):
        self.cookies = cookies
        self.url = url
        self._write_key = write_key
        self._enabled = enabled

    def _post(self, endpoint, data):
        # there is an issue with a timing condition with keep-alive
        # that is best explained here: https://github.com/mikem23/keepalive-race
        #
        #   If you make a request, wait just the right amount of time,
        #   then make another request, the requests module may opt to
        #   reuse the connection, but by the time the server gets it the
        #   timeout will have expired.
        #
        # by forcing the connection to close, we will disable the keep-alive.

        def update_cookies(response):
            self.cookies.update(response.cookies())
            return response

        assert endpoint[0] == '/'
        headers = {b"Connection": b"close"}
        d = treq.post(self.url + endpoint, auth=(self._write_key, ''), json=data,
                      headers=headers, cookies=self.cookies)
        d.addCallback(update_cookies)
        return d

    def track(self, event):
        """Send a single tracking event"""
        if not self._enabled:
            return defer.succeed('Analytics disabled')

        def _log_error(failure, event):
            log.warning('Failed to send track event. %s (%s)', failure.getTraceback(), str(event))

        log.debug('Sending track event: %s', event)
        d = self._post('/track', event)
        d.addErrback(_log_error, event)
        return d

    @classmethod
    def new_instance(cls, enabled=None):
        """Initialize an instance using values from the configuration"""
        if enabled is None:
            enabled = conf.settings['share_usage_data']
        return cls(
            {},
            conf.settings['ANALYTICS_ENDPOINT'],
            utils.deobfuscate(conf.settings['ANALYTICS_TOKEN']),
            enabled,
        )
