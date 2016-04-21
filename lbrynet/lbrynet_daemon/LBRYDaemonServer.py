import logging
import subprocess
import os
import shutil
import jsonrpc
import json

from StringIO import StringIO
from zipfile import ZipFile
from urllib import urlopen
from datetime import datetime
from appdirs import user_data_dir
from twisted.web import server, static, resource
from twisted.internet import defer

from lbrynet.lbrynet_daemon.LBRYDaemon import LBRYDaemon
from lbrynet.conf import API_CONNECTION_STRING, API_ADDRESS, DEFAULT_WALLET, UI_ADDRESS

log = logging.getLogger(__name__)

data_dir = user_data_dir("LBRY")
if not os.path.isdir(data_dir):
    os.mkdir(data_dir)
version_dir = os.path.join(data_dir, "ui_version_history")
if not os.path.isdir(version_dir):
    os.mkdir(version_dir)

version_log = logging.getLogger("lbry_version")
version_log.addHandler(logging.FileHandler(os.path.join(version_dir, "lbry_version.log")))
version_log.setLevel(logging.INFO)


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


class LBRYFileRender(resource.Resource):
    isLeaf = False

    def render_GET(self, request):
        if 'name' in request.args.keys():
            api = jsonrpc.Proxy(API_CONNECTION_STRING)
            if request.args['name'][0] != 'lbry':
                d = api.callRemote("get", {'name': request.args['name'][0]})
                d.addCallback(lambda results: static.File(results['path']).render_GET(request))
            else:
                request.redirect(UI_ADDRESS)
                request.finish()
            return server.NOT_DONE_YET
        else:
            return server.failure


class LBRYBugReport(resource.Resource):
    isLeaf = False

    def _delayed_render(self, request, results):
        request.write(results)
        request.finish()

    def render_GET(self, request):
        return '<html><body><form method="POST">' \
               '<br>Please describe the problem you experienced and any information you think might be useful to us. Links to screenshots are great!</br>' \
               '<textarea cols="50" rows="10" name="message" type="text"></textarea>' \
               '<button>Submit</button>' \
               '</form></body></html>'

    def render_POST(self, request):
        msg = request.args["message"][0]
        log.info("User submitted error report: " + str(msg))
        api = jsonrpc.Proxy(API_CONNECTION_STRING)
        d = api.callRemote("upload_log", {'name_prefix': 'report', 'exclude_previous': False, 'force': True})
        d.addCallback(lambda _: self._delayed_render(request, "<html><body>Your bug report is greatly appreciated! <a href='lbry://lbry'>Click here to return to LBRY</a></body></html>"))

        return server.NOT_DONE_YET


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
            except:
                self.loaded_git_version = None

    def setup(self, branch="HEAD", user_specified=None):
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
        elif branch == "HEAD":
            log.info("Using UI branch: " + branch)
            self._gitcmd = "git ls-remote https://github.com/lbryio/lbry-web-ui.git | grep %s | cut -f 1" % branch
            self._dist_url = "https://raw.githubusercontent.com/lbryio/lbry-web-ui/master/dist.zip"
        else:
            log.info("Using UI branch: " + branch)
            self._gitcmd = "git ls-remote https://github.com/lbryio/lbry-web-ui.git | grep refs/heads/%s | cut -f 1" % branch
            self._dist_url = "https://raw.githubusercontent.com/lbryio/lbry-web-ui/%s/dist.zip" % branch

        d = self._up_to_date()
        d.addCallback(lambda r: self._download_ui() if not r else self.branch)
        return d

    def _up_to_date(self):
        def _get_git_info():
            r = subprocess.check_output(self._gitcmd, shell=True)
            return defer.succeed(r)

        def _set_git(version):
            self.git_version = version
            log.info("UI version from git: " + str(self.git_version).replace("\n", ""))
            version_log.info("UI version from git: " + str(self.git_version).replace("\n", ""))

            if self.git_version == self.loaded_git_version and os.path.isdir(self.ui_dir):
                log.info("UI is up to date")
                version_log.info("UI is up to date")
                return defer.succeed(True)
            else:
                log.info("Downloading UI")
                version_log.info("Downloading UI")
                f = open(self.config, "w")
                f.write(json.dumps({'commit': self.git_version,
                                    'time': str(datetime.now())}))
                f.close()
                return defer.succeed(False)

        d = _get_git_info()
        d.addCallback(_set_git)
        return d

    def _download_ui(self):
        def _delete_ui_dir():
            if os.path.isdir(self.ui_dir):
                if self.loaded_git_version:
                    version_log.info("Removed ui files for commit " + str(self.loaded_git_version))
                log.info("Removing out of date ui files")
                shutil.rmtree(self.ui_dir)
            return defer.succeed(None)

        def _dl_ui():
            url = urlopen(self._dist_url)
            z = ZipFile(StringIO(url.read()))
            names = [i for i in z.namelist() if '.DS_exStore' not in i and '__MACOSX' not in i]
            z.extractall(self.ui_dir, members=names)
            version_log.info("[" + str(datetime.now()) + "] Updated branch " + self.branch + " commit: " + str(self.loaded_git_version) + " to " + self.git_version)
            log.info("Downloaded files for UI commit " + self.git_version)
            self.loaded_git_version = self.git_version
            return self.branch

        d = _delete_ui_dir()
        d.addCallback(lambda _: _dl_ui())
        return d

    def _setup_server(self, ui_ver):
        self._api = LBRYDaemon(ui_ver, wallet_type=DEFAULT_WALLET)
        self.root = LBRYindex(self.ui_dir)
        self.root.putChild("css", static.File(os.path.join(self.ui_dir, "css")))
        self.root.putChild("font", static.File(os.path.join(self.ui_dir, "font")))
        self.root.putChild("img", static.File(os.path.join(self.ui_dir, "img")))
        self.root.putChild("js", static.File(os.path.join(self.ui_dir, "js")))
        self.root.putChild("view", LBRYFileRender())
        self.root.putChild("report", LBRYBugReport())
        self.root.putChild(API_ADDRESS, self._api)
        return defer.succeed(True)

    def start(self, branch="HEAD", user_specified=False):
        d = self.setup(branch=branch, user_specified=user_specified)
        d.addCallback(lambda v: self._setup_server(v))
        d.addCallback(lambda _: self._api.setup())

        return d
