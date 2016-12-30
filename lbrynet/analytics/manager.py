from lbrynet.core import looping_call_manager

from twisted.internet import defer
from twisted.internet import task

from lbrynet.core.system_info import get_platform
from lbrynet.conf import settings

import constants
from api import Api
from events import Events, make_context
from track import Track


class Manager(object):
    def __init__(self, analytics_api, events_generator, track):
        self.analytics_api = analytics_api
        self.events_generator = events_generator
        self.track = track
        self.looping_call_manager = self.setup_looping_calls()
        self.is_started = False

    @classmethod
    def new_instance(cls, api=None, events=None):
        if api is None:
            api = Api.new_instance()
        if events is None:
            events = Events(
                make_context(get_platform(), settings.wallet),
                'not loaded', 'not loaded'
            )
        return cls(api, events, Track())

    def update_events_generator(self, events_generator):
        self.events_generator = events_generator

    def _get_looping_calls(self):
        return [
            ('send_heartbeat', self._send_heartbeat, 60),
            ('update_tracked_metrics', self._update_tracked_metrics, 300),
        ]

    def setup_looping_calls(self):
        call_manager = looping_call_manager.LoopingCallManager()
        for name, fn, _ in self._get_looping_calls():
            call_manager.register_looping_call(name, task.LoopingCall(fn))
        return call_manager

    def start(self):
        if not self.is_started:
            for name, _, interval in self._get_looping_calls():
                self.looping_call_manager.start(name, interval)
            self.is_started = True

    def shutdown(self):
        self.looping_call_manager.shutdown()

    def send_server_startup(self):
        event = self.events_generator.server_startup()
        self.analytics_api.track(event)

    def send_server_startup_success(self):
        event = self.events_generator.server_startup_success()
        self.analytics_api.track(event)

    def send_server_startup_error(self, message):
        event = self.events_generator.server_startup_error(message)
        self.analytics_api.track(event)

    def send_download_started(self, id_, name, stream_info=None):
        event = self.events_generator.download_started(id_, name, stream_info)
        self.analytics_api.track(event)

    def send_download_errored(self, id_, name, stream_info=None):
        event = self.events_generator.download_errored(id_, name, stream_info)
        self.analytics_api.track(event)

    def send_download_finished(self, id_, name, stream_info=None):
        event = self.events_generator.download_finished(id_, name, stream_info)
        self.analytics_api.track(event)

    def send_error(self, message, sd_hash=None):
        event = self.events_generator.error(message, sd_hash)
        self.analytics_api.track(event)

    def register_repeating_metric(self, event_name, value_generator, frequency=300):
        lcall = task.LoopingCall(self._send_repeating_metric, event_name, value_generator)
        self.looping_call_manager.register_looping_call(event_name, lcall)
        lcall.start(frequency)

    def _send_heartbeat(self):
        heartbeat = self.events_generator.heartbeat()
        self.analytics_api.track(heartbeat)

    def _update_tracked_metrics(self):
        should_send, value = self.track.summarize_and_reset(constants.BLOB_BYTES_UPLOADED)
        if should_send:
            event = self.events_generator.metric_observed(constants.BLOB_BYTES_UPLOADED, value)
            self.analytics_api.track(event)

    def _send_repeating_metric(self, event_name, value_generator):
        result = value_generator()
        if_deferred(result, self._send_repeating_metric_value, event_name)

    def _send_repeating_metric_value(self, result, event_name):
        should_send, value = result
        if should_send:
            event = self.events_generator.metric_observed(event_name, value)
            self.analytics_api.track(event)


def if_deferred(maybe_deferred, callback, *args, **kwargs):
    if isinstance(maybe_deferred, defer.Deferred):
        maybe_deferred.addCallback(callback, *args, **kwargs)
    else:
        callback(maybe_deferred, *args, **kwargs)
