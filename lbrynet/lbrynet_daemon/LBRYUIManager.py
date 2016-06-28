import os
import logging
import shutil
import sys
import json

from urllib2 import urlopen
from StringIO import StringIO
from twisted.web import static
from twisted.internet import defer
from lbrynet.conf import DEFAULT_UI_BRANCH, LOG_FILE_NAME
from lbrynet import __version__ as lbrynet_version
from lbryum.version import LBRYUM_VERSION as lbryum_version
from zipfile import ZipFile
from appdirs import user_data_dir

if sys.platform != "darwin":
    log_dir = os.path.join(os.path.expanduser("~"), ".lbrynet")
else:
    log_dir = user_data_dir("LBRY")

if not os.path.isdir(log_dir):
    os.mkdir(log_dir)

lbrynet_log = os.path.join(log_dir, LOG_FILE_NAME)
log = logging.getLogger(__name__)
handler = logging.handlers.RotatingFileHandler(lbrynet_log, maxBytes=2097152, backupCount=5)
log.addHandler(handler)
log.setLevel(logging.INFO)


class LBRYUIManager(object):
    def __init__(self, root):
        if sys.platform != "darwin":
            self.data_dir = os.path.join(os.path.expanduser("~"), '.lbrynet')
        else:
            self.data_dir = user_data_dir("LBRY")

        self.ui_root = os.path.join(self.data_dir, "lbry-ui")
        self.active_dir = os.path.join(self.ui_root, "active")
        self.update_dir = os.path.join(self.ui_root, "update")

        if not os.path.isdir(self.data_dir):
            os.mkdir(self.data_dir)
        if not os.path.isdir(self.ui_root):
            os.mkdir(self.ui_root)
        if not os.path.isdir(self.active_dir):
            os.mkdir(self.active_dir)
        if not os.path.isdir(self.update_dir):
            os.mkdir(self.update_dir)

        self.config = os.path.join(self.ui_root, "active.json")
        self.update_requires = os.path.join(self.update_dir, "requirements.txt")
        self.requirements = {}
        self.ui_dir = self.active_dir
        self.git_version = None
        self.root = root

        if not os.path.isfile(os.path.join(self.config)):
            self.loaded_git_version = None
            self.loaded_branch = None
            self.loaded_requirements = None
        else:
            try:
                f = open(self.config, "r")
                loaded_ui = json.loads(f.read())
                f.close()
                self.loaded_git_version = loaded_ui['commit']
                self.loaded_branch = loaded_ui['branch']
                self.loaded_requirements = loaded_ui['requirements']
            except:
                self.loaded_git_version = None
                self.loaded_branch = None
                self.loaded_requirements = None

    def setup(self, branch=DEFAULT_UI_BRANCH, user_specified=None, branch_specified=False):
        self.branch = branch
        if user_specified:
            if os.path.isdir(user_specified):
                log.info("Checking user specified UI directory: " + str(user_specified))
                self.branch = "user-specified"
                self.loaded_git_version = "user-specified"
                d = self.migrate_ui(source=user_specified)
                d.addCallback(lambda _: self._load_ui())
                return d
            else:
                log.info("User specified UI directory doesn't exist, using " + branch)
        elif self.loaded_branch == "user-specified" and not branch_specified:
            log.info("Loading user provided UI")
            d = self._load_ui()
            return d
        else:
            log.info("Checking for updates for UI branch: " + branch)
            self._git_url = "https://api.github.com/repos/lbryio/lbry-web-ui/git/refs/heads/%s" % branch
            self._dist_url = "https://raw.githubusercontent.com/lbryio/lbry-web-ui/%s/dist.zip" % branch

        d = self._up_to_date()
        d.addCallback(lambda r: self._download_ui() if not r else self._load_ui())
        return d

    def _up_to_date(self):
        def _get_git_info():
            response = urlopen(self._git_url)
            data = json.loads(response.read())
            return defer.succeed(data['object']['sha'])

        def _set_git(version):
            self.git_version = version.replace('\n', '')
            if self.git_version == self.loaded_git_version:
                log.info("UI is up to date")
                return defer.succeed(True)
            else:
                log.info("UI updates available, checking if installation meets requirements")
                return defer.succeed(False)

        d = _get_git_info()
        d.addCallback(_set_git)
        return d

    def migrate_ui(self, source=None):
        if not source:
            requires_file = self.update_requires
            source_dir = self.update_dir
            delete_source = True
        else:
            requires_file = os.path.join(source, "requirements.txt")
            source_dir = source
            delete_source = False

        def _check_requirements():
            if not os.path.isfile(requires_file):
                log.info("No requirements.txt file, rejecting request to migrate this UI")
                return defer.succeed(False)

            f = open(requires_file, "r")
            for requirement in [line for line in f.read().split('\n') if line]:
                t = requirement.split('=')
                if len(t) == 3:
                    self.requirements[t[0]] = {'version': t[1], 'operator': '=='}
                elif t[0][-1] == ">":
                    self.requirements[t[0][:-1]] = {'version': t[1], 'operator': '>='}
                elif t[0][-1] == "<":
                    self.requirements[t[0][:-1]] = {'version': t[1], 'operator': '<='}
            f.close()
            passed_requirements = True
            for r in self.requirements:
                if r == 'lbrynet':
                    c = lbrynet_version
                elif r == 'lbryum':
                    c = lbryum_version
                else:
                    c = None
                if c:
                    if self.requirements[r]['operator'] == '==':
                        if not self.requirements[r]['version'] == c:
                            passed_requirements = False
                            log.info("Local version %s of %s does not meet UI requirement for version %s" % (
                            c, r, self.requirements[r]['version']))
                        else:
                            log.info("Local version of %s meets ui requirement" % r)
                    if self.requirements[r]['operator'] == '>=':
                        if not self.requirements[r]['version'] <= c:
                            passed_requirements = False
                            log.info("Local version %s of %s does not meet UI requirement for version %s" % (
                            c, r, self.requirements[r]['version']))
                        else:
                            log.info("Local version of %s meets ui requirement" % r)
                    if self.requirements[r]['operator'] == '<=':
                        if not self.requirements[r]['version'] >= c:
                            passed_requirements = False
                            log.info("Local version %s of %s does not meet UI requirement for version %s" % (
                            c, r, self.requirements[r]['version']))
                        else:
                            log.info("Local version of %s meets ui requirement" % r)
            return defer.succeed(passed_requirements)

        def _disp_failure():
            log.info("Failed to satisfy requirements for branch '%s', update was not loaded" % self.branch)
            return defer.succeed(False)

        def _do_migrate():
            if os.path.isdir(self.active_dir):
                shutil.rmtree(self.active_dir)
            shutil.copytree(source_dir, self.active_dir)
            if delete_source:
                shutil.rmtree(source_dir)

            log.info("Loaded UI update")

            f = open(self.config, "w")
            loaded_ui = {'commit': self.git_version, 'branch': self.branch, 'requirements': self.requirements}
            f.write(json.dumps(loaded_ui))
            f.close()

            self.loaded_git_version = loaded_ui['commit']
            self.loaded_branch = loaded_ui['branch']
            self.loaded_requirements = loaded_ui['requirements']
            return defer.succeed(True)

        d = _check_requirements()
        d.addCallback(lambda r: _do_migrate() if r else _disp_failure())
        return d

    def _download_ui(self):
        def _delete_update_dir():
            if os.path.isdir(self.update_dir):
                shutil.rmtree(self.update_dir)
            return defer.succeed(None)

        def _dl_ui():
            url = urlopen(self._dist_url)
            z = ZipFile(StringIO(url.read()))
            names = [i for i in z.namelist() if '.DS_exStore' not in i and '__MACOSX' not in i]
            z.extractall(self.update_dir, members=names)
            log.info("Downloaded files for UI commit " + str(self.git_version).replace("\n", ""))
            return self.branch

        d = _delete_update_dir()
        d.addCallback(lambda _: _dl_ui())
        d.addCallback(lambda _: self.migrate_ui())
        d.addCallback(lambda _: self._load_ui())
        return d

    def _load_ui(self):
        for d in [i[0] for i in os.walk(self.active_dir) if os.path.dirname(i[0]) == self.active_dir]:
            self.root.putChild(os.path.basename(d), static.File(d))
        return defer.succeed(True)