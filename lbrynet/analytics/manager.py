import base58

from twisted.internet import task

import api
import constants
import events
import track


class Manager(object):
    def __init__(self):
        self.analytics_api = None
        self.events_generator = None
        self.track = track.Track()
        self.send_heartbeat = task.LoopingCall(self._send_heartbeat)
        self.update_tracked_metrics = task.LoopingCall(self._update_tracked_metrics)

    def start(self, platform, wallet_type, lbry_id, session_id):
        context = events.make_context(platform, wallet_type)
        self.events_generator = events.Events(context, base58.b58encode(lbry_id), session_id)
        self.analytics_api = api.Api.load()
        self.send_heartbeat.start(60)
        self.update_tracked_metrics.start(300)

    def shutdown(self):
        if self.send_heartbeat.running:
            self.send_heartbeat.stop()
        if self.update_tracked_metrics.running:
            self.update_tracked_metrics.stop()

    def send_download_started(self, name, stream_info=None):
        event = self.events_generator.download_started(name, stream_info)
        self.analytics_api.track(event)

    def _send_heartbeat(self):
        heartbeat = self.events_generator.heartbeat()
        self.analytics_api.track(heartbeat)

    def _update_tracked_metrics(self):
        value = self.track.summarize(constants.BLOB_BYTES_UPLOADED)
        if value > 0:
            event = self.events_generator.metric_observered(constants.BLOB_BYTES_UPLOADED, value)
            self.analytics_api.track(event)
