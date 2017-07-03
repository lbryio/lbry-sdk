import logging
import os
import shutil
import json
import tempfile


from twisted.web import server, static, resource
from twisted.internet import defer, error

from lbrynet import conf
from lbrynet.daemon.FileStreamer import EncryptedFileStreamer

log = logging.getLogger(__name__)


class NoCacheStaticFile(static.File):
    def _set_no_cache(self, request):
        request.setHeader('cache-control', 'no-cache, no-store, must-revalidate')
        request.setHeader('expires', '0')

    def render_GET(self, request):
        self._set_no_cache(request)
        return static.File.render_GET(self, request)


class LBRYindex(resource.Resource):
    def __init__(self, ui_dir):
        resource.Resource.__init__(self)
        self.ui_dir = ui_dir

    isLeaf = False

    def _delayed_render(self, request, results):
        request.write(str(results))
        request.finish()

    def getChild(self, name, request):
        request.setHeader('cache-control', 'no-cache, no-store, must-revalidate')
        request.setHeader('expires', '0')

        if name == '':
            return self
        return resource.Resource.getChild(self, name, request)

    def render_GET(self, request):
        return NoCacheStaticFile(os.path.join(self.ui_dir, "index.html")).render_GET(request)


class HostedEncryptedFile(resource.Resource):
    def __init__(self, api):
        self._api = api
        resource.Resource.__init__(self)

    def _make_stream_producer(self, request, stream):
        path = os.path.join(self._api.download_directory, stream.file_name)

        producer = EncryptedFileStreamer(request, path, stream, self._api.lbry_file_manager)
        request.registerProducer(producer, streaming=True)

        d = request.notifyFinish()
        d.addErrback(self._responseFailed, d)
        return d

    def is_valid_request_name(self, request):
        return (
            request.args['name'][0] != 'lbry' and
            request.args['name'][0] not in self._api.waiting_on.keys())

    def render_GET(self, request):
        request.setHeader("Content-Security-Policy", "sandbox")
        if 'name' in request.args.keys():
            if self.is_valid_request_name(request):
                name = request.args['name'][0]
                d = self._api.jsonrpc_get(name=name)
                d.addCallback(lambda response: response['stream_hash'])
                d.addCallback(lambda sd_hash: self._api._get_lbry_file_by_sd_hash(sd_hash))
                d.addCallback(lambda lbry_file: self._make_stream_producer(request, lbry_file))
            elif request.args['name'][0] in self._api.waiting_on.keys():
                request.redirect(
                    conf.settings.get_ui_address() + "/?watch=" + request.args['name'][0]
                )
                request.finish()
            else:
                request.redirect(conf.settings.get_ui_address())
                request.finish()
            return server.NOT_DONE_YET

    def _responseFailed(self, err, call):
        call.addErrback(lambda err: err.trap(error.ConnectionDone))
        call.addErrback(lambda err: err.trap(defer.CancelledError))
        call.addErrback(lambda err: log.info("Error: " + str(err)))
        call.cancel()


class EncryptedFileUpload(resource.Resource):
    """
    Accepts a file sent via the file upload widget in the web UI, saves
    it into a temporary dir, and responds with a JSON string containing
    the path of the newly created file.
    """
    def __init__(self, api):
        self._api = api

    def render_POST(self, request):
        origfilename = request.args['file_filename'][0]
        # Temp file created by request
        uploaded_file = request.args['file'][0]
        newpath = move_to_temp_dir_and_restore_filename(uploaded_file, origfilename)
        self._api.uploaded_temp_files.append(newpath)
        return json.dumps(newpath)


def move_to_temp_dir_and_restore_filename(uploaded_file, origfilename):
    newdirpath = tempfile.mkdtemp()
    newpath = os.path.join(newdirpath, origfilename)
    if os.name == "nt":
        # TODO: comment on why shutil.move doesn't work?
        move_win(uploaded_file.name, newpath)
    else:
        shutil.move(uploaded_file.name, newpath)
    return newpath


def move_win(from_path, to_path):
    shutil.copy(from_path, to_path)
    # TODO Still need to remove the file
    # TODO deal with pylint error in cleaner fashion than this
    try:
        from exceptions import WindowsError as win_except
    except ImportError as e:
        log.error("This shouldn't happen")
        win_except = Exception
    try:
        os.remove(from_path)
    except win_except as e:
        pass
