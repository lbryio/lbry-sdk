import logging
import os
import shutil
import json
import sys
import mimetypes

from StringIO import StringIO
from zipfile import ZipFile
from urllib import urlopen
from datetime import datetime
from appdirs import user_data_dir
from twisted.web import server, static, resource
from twisted.internet import defer, interfaces, error, reactor, task, threads
from twisted.python.failure import Failure
from txjsonrpc.web import jsonrpc

from zope.interface import implements

from lbrynet.lbrynet_daemon.LBRYDaemon import LBRYDaemon
from lbrynet.conf import API_CONNECTION_STRING, API_ADDRESS, DEFAULT_WALLET, UI_ADDRESS


if sys.platform != "darwin":
    data_dir = os.path.join(os.path.expanduser("~"), ".lbrynet")
else:
    data_dir = user_data_dir("LBRY")

if not os.path.isdir(data_dir):
    os.mkdir(data_dir)
version_dir = os.path.join(data_dir, "ui_version_history")
if not os.path.isdir(version_dir):
    os.mkdir(version_dir)

version_log = logging.getLogger("lbry_version")
version_log.addHandler(logging.FileHandler(os.path.join(version_dir, "lbry_version.log")))
version_log.setLevel(logging.INFO)
log = logging.getLogger(__name__)
log.addHandler(logging.FileHandler(os.path.join(data_dir, 'lbrynet-daemon.log')))
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

    def makeProducer(self, request, stream):
        def _save_producer(producer):
            self._producer = producer
            return defer.succeed(None)

        range_header = request.getAllHeaders()['range'].replace('bytes=', '').split('-')
        start, stop = int(range_header[0]), range_header[1]
        log.info("[" + str(datetime.now()) + "] GET range %s-%s" % (start, stop))
        path = os.path.join(self._api.download_directory, stream.file_name)

        d = stream.get_total_bytes()
        d.addCallback(lambda size: _save_producer(LBRYFileStreamer(request, path, start, stop, size)))
        d.addCallback(lambda _: request.registerProducer(self._producer, streaming=True))
        # request.notifyFinish().addCallback(lambda _: self._producer.stopProducing())
        request.notifyFinish().addErrback(self._responseFailed, d)
        return d

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

    def _responseFailed(self, err, call):
        call.addErrback(lambda err: err.trap(error.ConnectionDone))
        call.addErrback(lambda err: err.trap(defer.CancelledError))
        call.addErrback(lambda err: log.info("Error: " + str(err)))
        call.cancel()


class MyLBRYFiles(resource.Resource):
    isLeaf = False

    def __init__(self):
        resource.Resource.__init__(self)
        self.files_table = None

    def delayed_render(self, request, result):
        request.write(result.encode('utf-8'))
        request.finish()

    def render_GET(self, request):
        self.files_table = None
        api = jsonrpc.Proxy(API_CONNECTION_STRING)
        d = api.callRemote("get_lbry_files", {})
        d.addCallback(self._get_table)
        d.addCallback(lambda results: self.delayed_render(request, results))

        return server.NOT_DONE_YET

    def _get_table(self, files):
        if not self.files_table:
            self.files_table = r'<html><head><title>My LBRY files</title></head><body><table border="1">'
            self.files_table += r'<tr>'
            self.files_table += r'<td>Stream name</td>'
            self.files_table += r'<td>Completed</td>'
            self.files_table += r'<td>Toggle</td>'
            self.files_table += r'<td>Remove</td>'
            self.files_table += r'</tr>'
            return self._get_table(files)
        if not len(files):
            self.files_table += r'</table></body></html>'
            return self.files_table
        else:
            f = files.pop()
            self.files_table += r'<tr>'
            self.files_table += r'<td>%s</td>' % (f['stream_name'])
            self.files_table += r'<td>%s</td>' % (f['completed'])
            self.files_table += r'<td>Start</td>' if f['stopped'] else r'<td>Stop</td>'
            self.files_table += r'<td>Delete</td>'
            self.files_table += r'</tr>'
            return self._get_table(files)


class LBRYDaemonServer(object):
    def __init__(self):
        self.data_dir = user_data_dir("LBRY")
        if not os.path.isdir(self.data_dir):
            os.mkdir(self.data_dir)
        self.version_dir = os.path.join(self.data_dir, "ui_version_history")
        if not os.path.isdir(self.version_dir):
            os.mkdir(self.version_dir)
        self.config = os.path.join(self.version_dir, "active.json")
        self.ui_dir = os.path.join(self.data_dir, "lbry-web-ui")
        self.git_version = None
        self._api = None
        self.root = None

        if not os.path.isfile(os.path.join(self.config)):
            self.loaded_git_version = None
        else:
            try:
                f = open(self.config, "r")
                loaded_ui = json.loads(f.read())
                f.close()
                self.loaded_git_version = loaded_ui['commit']
                self.loaded_branch = loaded_ui['branch']
                version_log.info("[" + str(datetime.now()) + "] Last used " + self.loaded_branch + " commit " + str(self.loaded_git_version).replace("\n", ""))
            except:
                self.loaded_git_version = None
                self.loaded_branch = None

    def setup(self, branch="master", user_specified=None):
        self.branch = branch
        if user_specified:
            if os.path.isdir(user_specified):
                log.info("Using user specified UI directory: " + str(user_specified))
                self.branch = "user-specified"
                self.loaded_git_version = "user-specified"
                self.ui_dir = user_specified
                return defer.succeed("user-specified")
            else:
                log.info("User specified UI directory doesn't exist, using " + branch)
        else:
            log.info("Using UI branch: " + branch)
            self._git_url = "https://api.github.com/repos/lbryio/lbry-web-ui/git/refs/heads/%s" % branch
            self._dist_url = "https://raw.githubusercontent.com/lbryio/lbry-web-ui/%s/dist.zip" % branch

        d = self._up_to_date()
        d.addCallback(lambda r: self._download_ui() if not r else self.branch)
        return d

    def _up_to_date(self):
        def _get_git_info():
            response = urlopen(self._git_url)
            data = json.loads(response.read())
            return defer.succeed(data['object']['sha'])

        def _set_git(version):
            self.git_version = version
            version_log.info("[" + str(datetime.now()) + "] UI branch " + self.branch + " has a most recent commit of: " + str(self.git_version).replace("\n", ""))

            if self.git_version == self.loaded_git_version and os.path.isdir(self.ui_dir):
                version_log.info("[" + str(datetime.now()) + "] local copy of " + self.branch + " is up to date")
                return defer.succeed(True)
            else:
                if self.git_version == self.loaded_git_version:
                    version_log.info("[" + str(datetime.now()) + "] Can't find ui files, downloading them again")
                else:
                    version_log.info("[" + str(datetime.now()) + "] local copy of " + self.branch + " branch is out of date, updating")
                f = open(self.config, "w")
                f.write(json.dumps({'commit': self.git_version,
                                    'time': str(datetime.now()),
                                    'branch': self.branch}))
                f.close()
                return defer.succeed(False)

        d = _get_git_info()
        d.addCallback(_set_git)
        return d

    def _download_ui(self):
        def _delete_ui_dir():
            if os.path.isdir(self.ui_dir):
                if self.loaded_git_version:
                    version_log.info("[" + str(datetime.now()) + "] Removed ui files for commit " + str(self.loaded_git_version).replace("\n", ""))
                log.info("Removing out of date ui files")
                shutil.rmtree(self.ui_dir)
            return defer.succeed(None)

        def _dl_ui():
            url = urlopen(self._dist_url)
            z = ZipFile(StringIO(url.read()))
            names = [i for i in z.namelist() if '.DS_exStore' not in i and '__MACOSX' not in i]
            z.extractall(self.ui_dir, members=names)
            version_log.info("[" + str(datetime.now()) + "] Updated branch " + self.branch + ": " + str(self.loaded_git_version).replace("\n", "") + " --> " + self.git_version.replace("\n", ""))
            log.info("Downloaded files for UI commit " + str(self.git_version).replace("\n", ""))
            self.loaded_git_version = self.git_version
            return self.branch

        d = _delete_ui_dir()
        d.addCallback(lambda _: _dl_ui())
        return d

    def _setup_server(self, ui_ver, wallet):
        self._api = LBRYDaemon(ui_ver, wallet_type=wallet)
        self.root = LBRYindex(self.ui_dir)
        self.root.putChild("css", static.File(os.path.join(self.ui_dir, "css")))
        self.root.putChild("font", static.File(os.path.join(self.ui_dir, "font")))
        self.root.putChild("img", static.File(os.path.join(self.ui_dir, "img")))
        self.root.putChild("js", static.File(os.path.join(self.ui_dir, "js")))
        self.root.putChild("view", HostedLBRYFile(self._api))
        self.root.putChild("files", MyLBRYFiles())
        self.root.putChild(API_ADDRESS, self._api)
        return defer.succeed(True)

    def start(self, branch="master", user_specified=False, wallet=DEFAULT_WALLET):
        d = self.setup(branch=branch, user_specified=user_specified)
        d.addCallback(lambda v: self._setup_server(v, wallet))
        d.addCallback(lambda _: self._api.setup())

        return d
