import logging
import os
import shutil
import json
import sys
import mimetypes

from datetime import datetime
from appdirs import user_data_dir
from twisted.web import server, static, resource
from twisted.internet import defer, interfaces, error, reactor, task, threads

from zope.interface import implements

from lbrynet.lbrynet_daemon.LBRYDaemon import LBRYDaemon
from lbrynet.conf import API_CONNECTION_STRING, API_ADDRESS, DEFAULT_WALLET, UI_ADDRESS, DEFAULT_UI_BRANCH, LOG_FILE_NAME


if sys.platform != "darwin":
    data_dir = os.path.join(os.path.expanduser("~"), ".lbrynet")
else:
    data_dir = user_data_dir("LBRY")
if not os.path.isdir(data_dir):
    os.mkdir(data_dir)

lbrynet_log = os.path.join(data_dir, LOG_FILE_NAME)
log = logging.getLogger(__name__)
handler = logging.handlers.RotatingFileHandler(lbrynet_log, maxBytes=2097152, backupCount=5)
log.addHandler(handler)
log.setLevel(logging.INFO)


class LBRYindex(resource.Resource):
    def __init__(self, ui_dir):
        resource.Resource.__init__(self)
        self.ui_dir = ui_dir

    isLeaf = False

    def _delayed_render(self, request, results):
        request.write(str(results))
        request.finish()

    def getChild(self, name, request):
        if name == '':
            return self
        return resource.Resource.getChild(self, name, request)

    def render_GET(self, request):
        return static.File(os.path.join(self.ui_dir, "index.html")).render_GET(request)


class LBRYFileStreamer(object):
    """
    Writes downloaded LBRY file to request as the download comes in, pausing and resuming as requested
    used for Chrome
    """

    implements(interfaces.IPushProducer)

    def __init__(self, request, path, start, stop, size):
        self._request = request
        self._fileObject = file(path)
        self._content_type = mimetypes.guess_type(path)[0]
        self._stop_pos = size - 1 if stop == '' else int(stop)  #chrome and firefox send range requests for "0-"
        self._cursor = self._start_pos = int(start)
        self._file_size = size
        self._depth = 0

        self._paused = self._sent_bytes = self._stopped = False
        self._delay = 0.25
        self._deferred = defer.succeed(None)

        self._request.setResponseCode(206)
        self._request.setHeader('accept-ranges', 'bytes')
        self._request.setHeader('content-type', self._content_type)

        self.resumeProducing()

    def pauseProducing(self):
        self._paused = True
        log.info("[" + str(datetime.now()) + "] Pausing producer")
        return defer.succeed(None)

    def resumeProducing(self):
        def _check_for_new_data():
            self._depth += 1
            self._fileObject.seek(self._start_pos, os.SEEK_END)
            readable_bytes = self._fileObject.tell()
            self._fileObject.seek(self._cursor)

            self._sent_bytes = False

            if (readable_bytes > self._cursor) and not (self._stopped or self._paused):
                read_length = min(readable_bytes, self._stop_pos) - self._cursor + 1
                self._request.setHeader('content-range', 'bytes %s-%s/%s' % (self._cursor, self._cursor + read_length - 1, self._file_size))
                self._request.setHeader('content-length', str(read_length))
                start_cur = self._cursor
                for i in range(read_length):
                    if self._paused or self._stopped:
                        break
                    else:
                        data = self._fileObject.read(1)
                        self._request.write(data)
                        self._cursor += 1

                log.info("[" + str(datetime.now()) + "] Wrote range %s-%s/%s, length: %s, readable: %s, depth: %s"  %
                         (start_cur, self._cursor, self._file_size, self._cursor - start_cur, readable_bytes, self._depth))
                self._sent_bytes = True

            if self._cursor == self._stop_pos + 1:
                self.stopProducing()
                return defer.succeed(None)
            elif self._paused or self._stopped:
                return defer.succeed(None)
            else:
                self._deferred.addCallback(lambda _: threads.deferToThread(reactor.callLater, self._delay, _check_for_new_data))
                return defer.succeed(None)

        log.info("[" + str(datetime.now()) + "] Resuming producer")
        self._paused = False
        self._deferred.addCallback(lambda _: _check_for_new_data())

    def stopProducing(self):
        log.info("[" + str(datetime.now()) + "] Stopping producer")
        self._stopped = True
        # self._fileObject.close()
        self._deferred.addErrback(lambda err: err.trap(defer.CancelledError))
        self._deferred.addErrback(lambda err: err.trap(error.ConnectionDone))
        self._deferred.cancel()
        # self._request.finish()
        self._request.unregisterProducer()
        return defer.succeed(None)


class HostedLBRYFile(resource.Resource):
    def __init__(self, api):
        self._api = api
        self._producer = None
        resource.Resource.__init__(self)

    # todo: fix LBRYFileStreamer and use it instead of static.File
    # def makeProducer(self, request, stream):
    #     def _save_producer(producer):
    #         self._producer = producer
    #         return defer.succeed(None)
    #
    #     range_header = request.getAllHeaders()['range'].replace('bytes=', '').split('-')
    #     start, stop = int(range_header[0]), range_header[1]
    #     log.info("[" + str(datetime.now()) + "] GET range %s-%s" % (start, stop))
    #     path = os.path.join(self._api.download_directory, stream.file_name)
    #
    #     d = stream.get_total_bytes()
    #     d.addCallback(lambda size: _save_producer(LBRYFileStreamer(request, path, start, stop, size)))
    #     d.addCallback(lambda _: request.registerProducer(self._producer, streaming=True))
    #     # request.notifyFinish().addCallback(lambda _: self._producer.stopProducing())
    #     request.notifyFinish().addErrback(self._responseFailed, d)
    #     return d

    def render_GET(self, request):
        if 'name' in request.args.keys():
            if request.args['name'][0] != 'lbry' and request.args['name'][0] not in self._api.waiting_on.keys():
                d = self._api._download_name(request.args['name'][0])
                # d.addCallback(lambda stream: self.makeProducer(request, stream))
                d.addCallback(lambda stream: static.File(os.path.join(self._api.download_directory,
                                                                          stream.file_name)).render_GET(request))

            elif request.args['name'][0] in self._api.waiting_on.keys():
                request.redirect(UI_ADDRESS + "/?watch=" + request.args['name'][0])
                request.finish()
            else:
                request.redirect(UI_ADDRESS)
                request.finish()
            return server.NOT_DONE_YET

    # def _responseFailed(self, err, call):
    #     call.addErrback(lambda err: err.trap(error.ConnectionDone))
    #     call.addErrback(lambda err: err.trap(defer.CancelledError))
    #     call.addErrback(lambda err: log.info("Error: " + str(err)))
    #     call.cancel()


class LBRYDaemonServer(object):
    def _setup_server(self, wallet):
        self.root = LBRYindex(os.path.join(os.path.join(data_dir, "lbry-ui"), "active"))
        self._api = LBRYDaemon(self.root, wallet_type=wallet)
        self.root.putChild("view", HostedLBRYFile(self._api))
        self.root.putChild(API_ADDRESS, self._api)
        return defer.succeed(True)

    def start(self, branch=DEFAULT_UI_BRANCH, user_specified=False, branch_specified=False, wallet=None):
        d = self._setup_server(wallet)
        d.addCallback(lambda _: self._api.setup(branch, user_specified, branch_specified))
        return d
