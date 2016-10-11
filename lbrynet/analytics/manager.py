from lbrynet.core import looping_call_manager

from twisted.internet import defer
from twisted.internet import task

import constants


class Manager(object):
    def __init__(self, analytics_api, events_generator, track):
        self.analytics_api = analytics_api
        self.events_generator = events_generator
        self.track = track
        self.looping_call_manager = self.setup_looping_calls()

    def setup_looping_calls(self):
        call_manager = looping_call_manager.LoopingCallManager()
        looping_calls = [
            ('send_heartbeat', self._send_heartbeat),
            ('update_tracked_metrics', self._update_tracked_metrics),
        ]
        for name, fn in looping_calls:
            call_manager.register_looping_call(name, task.LoopingCall(fn))
        return call_manager

    def start(self):
        self.looping_call_manager.start('send_heartbeat', 60)
        self.looping_call_manager.start('update_tracked_metrics', 300)

    def shutdown(self):
        self.looping_call_manager.shutdown()

    def send_download_started(self, name, stream_info=None):
        event = self.events_generator.download_started(name, stream_info)
        self.analytics_api.track(event)

    def register_repeating_metric(self, event_name, value_generator, frequency=300):
        lcall = task.LoopingCall(self._send_repeating_metric, event_name, value_generator)
        self.looping_call_manager.register_looping_call(event_name, lcall)
        lcall.start(frequency)

    def _send_heartbeat(self):
        heartbeat = self.events_generator.heartbeat()
        self.analytics_api.track(heartbeat)

    def _update_tracked_metrics(self):
        should_send, value = self.track.summarize(constants.BLOB_BYTES_UPLOADED)
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
        callback(mabye_deferred, *args, **kwargs)
