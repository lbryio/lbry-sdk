import logging
import os
import shutil
import json
import sys
import mimetypes
import mimetools
import tempfile
import time
import cgi

from appdirs import user_data_dir
from twisted.web import server, static, resource
from twisted.internet import defer, interfaces, error, reactor, threads

from zope.interface import implements

from lbrynet.lbrynet_daemon.LBRYDaemon import LBRYDaemon
from lbrynet.conf import API_ADDRESS, UI_ADDRESS, DEFAULT_UI_BRANCH, LOG_FILE_NAME


# TODO: omg, this code is essentially duplicated in LBRYDaemon
if sys.platform != "darwin":
    data_dir = os.path.join(os.path.expanduser("~"), ".lbrynet")
else:
    data_dir = user_data_dir("LBRY")
if not os.path.isdir(data_dir):
    os.mkdir(data_dir)

lbrynet_log = os.path.join(data_dir, LOG_FILE_NAME)
log = logging.getLogger(__name__)


class LBRYDaemonRequest(server.Request):
    """
    For LBRY specific request functionality. Currently just provides
    handling for large multipart POST requests, taken from here:
    http://sammitch.ca/2013/07/handling-large-requests-in-twisted/

    For multipart POST requests, this populates self.args with temp
    file objects instead of strings. Note that these files don't auto-delete
    on close because we want to be able to move and rename them.

    """

    # max amount of memory to allow any ~single~ request argument [ie: POSTed file]
    # note: this value seems to be taken with a grain of salt, memory usage may spike
    #       FAR above this value in some cases.
    #       eg: set the memory limit to 5 MB, write 2 blocks of 4MB, mem usage will
    #           have spiked to 8MB before the data is rolled to disk after the
    #           second write completes.
    memorylimit = 1024*1024*100

    # enable/disable debug logging
    do_log = False

    # re-defined only for debug/logging purposes
    def gotLength(self, length):
        if self.do_log:
            print '%f Headers received, Content-Length: %d' % (time.time(), length)
        server.Request.gotLength(self, length)

    # re-definition of twisted.web.server.Request.requestreceived, the only difference
    # is that self.parse_multipart() is used rather than cgi.parse_multipart()
    def requestReceived(self, command, path, version):
        from twisted.web.http import parse_qs
        if self.do_log:
            print '%f Request Received' % time.time()

        self.content.seek(0,0)
        self.args = {}
        self.stack = []

        self.method, self.uri = command, path
        self.clientproto = version
        x = self.uri.split(b'?', 1)

        if len(x) == 1:
            self.path = self.uri
        else:
            self.path, argstring = x
            self.args = parse_qs(argstring, 1)

        # cache the client and server information, we'll need this later to be
        # serialized and sent with the request so CGIs will work remotely
        self.client = self.channel.transport.getPeer()
        self.host = self.channel.transport.getHost()

        # Argument processing
        args = self.args
        ctype = self.requestHeaders.getRawHeaders(b'content-type')
        if ctype is not None:
            ctype = ctype[0]

        if self.method == b"POST" and ctype:
            mfd = b'multipart/form-data'
            key, pdict = cgi.parse_header(ctype)
            if key == b'application/x-www-form-urlencoded':
                args.update(parse_qs(self.content.read(), 1))
            elif key == mfd:
                try:
                    self.content.seek(0,0)
                    args.update(self.parse_multipart(self.content, pdict))
                    #args.update(cgi.parse_multipart(self.content, pdict))

                except KeyError as e:
                    if e.args[0] == b'content-disposition':
                        # Parse_multipart can't cope with missing
                        # content-dispostion headers in multipart/form-data
                        # parts, so we catch the exception and tell the client
                        # it was a bad request.
                        self.channel.transport.write(
                                b"HTTP/1.1 400 Bad Request\r\n\r\n")
                        self.channel.transport.loseConnection()
                        return
                    raise

            self.content.seek(0, 0)

        self.process()

    # re-definition of cgi.parse_multipart that uses a single temporary file to store
    # data rather than storing 2 to 3 copies in various lists.
    def parse_multipart(self, fp, pdict):
        if self.do_log:
            print '%f Parsing Multipart data: ' % time.time()
        rewind = fp.tell() #save cursor
        fp.seek(0,0) #reset cursor

        boundary = ""
        if 'boundary' in pdict:
            boundary = pdict['boundary']
        if not cgi.valid_boundary(boundary):
            raise ValueError,  ('Invalid boundary in multipart form: %r'
                                % (boundary,))

        nextpart = "--" + boundary
        lastpart = "--" + boundary + "--"
        partdict = {}
        terminator = ""

        while terminator != lastpart:
            c_bytes = -1

            data = tempfile.NamedTemporaryFile(delete=False)
            if terminator:
                # At start of next part.  Read headers first.
                headers = mimetools.Message(fp)
                clength = headers.getheader('content-length')
                if clength:
                    try:
                        c_bytes = int(clength)
                    except ValueError:
                        pass
                if c_bytes > 0:
                    data.write(fp.read(c_bytes))
            # Read lines until end of part.
            while 1:
                line = fp.readline()
                if not line:
                    terminator = lastpart # End outer loop
                    break
                if line[:2] == "--":
                    terminator = line.strip()
                    if terminator in (nextpart, lastpart):
                        break
                data.write(line)
            # Done with part.
            if data.tell() == 0:
                continue
            if c_bytes < 0:
                # if a Content-Length header was not supplied with the MIME part
                # then the trailing line break must be removed.
                # we have data, read the last 2 bytes
                rewind = min(2, data.tell())
                data.seek(-rewind, os.SEEK_END)
                line = data.read(2)
                if line[-2:] == "\r\n":
                    data.seek(-2, os.SEEK_END)
                    data.truncate()
                elif line[-1:] == "\n":
                    data.seek(-1, os.SEEK_END)
                    data.truncate()

            line = headers['content-disposition']
            if not line:
                continue
            key, params = cgi.parse_header(line)
            if key != 'form-data':
                continue
            if 'name' in params:
                name = params['name']
                # kludge in the filename
                if 'filename' in params:
                    fname_index = name + '_filename'
                    if fname_index in partdict:
                        partdict[fname_index].append(params['filename'])
                    else:
                        partdict[fname_index] = [params['filename']]
            else:
                # Unnamed parts are not returned at all.
                continue
            data.seek(0,0)
            if name in partdict:
                partdict[name].append(data)
            else:
                partdict[name] = [data]

        fp.seek(rewind)  # Restore cursor
        return partdict

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
        log.info("Pausing producer")
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

                log.info("Wrote range %s-%s/%s, length: %s, readable: %s, depth: %s"  %
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

        log.info("Resuming producer")
        self._paused = False
        self._deferred.addCallback(lambda _: _check_for_new_data())

    def stopProducing(self):
        log.info("Stopping producer")
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
    #     log.info("GET range %s-%s" % (start, stop))
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

class LBRYFileUpload(resource.Resource):
    """
    Accepts a file sent via the file upload widget in the web UI, saves
    it into a temporary dir, and responds with a JSON string containing
    the path of the newly created file.
    """

    def __init__(self, api):
        self._api = api

    def render_POST(self, request):
        origfilename = request.args['file_filename'][0]
        uploaded_file = request.args['file'][0]  # Temp file created by request

        # Move to a new temporary dir and restore the original file name
        newdirpath = tempfile.mkdtemp()
        newpath = os.path.join(newdirpath, origfilename)
        shutil.move(uploaded_file.name, newpath)
        self._api.uploaded_temp_files.append(newpath)

        return json.dumps(newpath)


class LBRYDaemonServer(object):
    def _setup_server(self, wallet):
        self.root = LBRYindex(os.path.join(os.path.join(data_dir, "lbry-ui"), "active"))
        self._api = LBRYDaemon(self.root, wallet_type=wallet)
        self.root.putChild("view", HostedLBRYFile(self._api))
        self.root.putChild("upload", LBRYFileUpload(self._api))
        self.root.putChild(API_ADDRESS, self._api)
        return defer.succeed(True)

    def start(self, branch=DEFAULT_UI_BRANCH, user_specified=False, branch_specified=False, wallet=None):
        d = self._setup_server(wallet)
        d.addCallback(lambda _: self._api.setup(branch, user_specified, branch_specified))
        return d
