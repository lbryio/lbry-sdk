import os
import logging
import shutil
import json
from urllib2 import urlopen
from StringIO import StringIO
from zipfile import ZipFile

import pkg_resources
from twisted.internet import defer
from twisted.internet.task import LoopingCall

from lbrynet import conf
from lbrynet.lbrynet_daemon.Resources import NoCacheStaticFile
from lbrynet import __version__ as lbrynet_version
from lbryum.version import LBRYUM_VERSION as lbryum_version



log = logging.getLogger(__name__)


class UIManager(object):
    def __init__(self, root):
        self.ui_root = os.path.join(conf.settings.data_dir, "lbry-ui")
        self.active_dir = os.path.join(self.ui_root, "active")
        self.update_dir = os.path.join(self.ui_root, "update")

        if not os.path.isdir(self.ui_root):
            os.mkdir(self.ui_root)
        if not os.path.isdir(self.active_dir):
            os.mkdir(self.active_dir)
        if not os.path.isdir(self.update_dir):
            os.mkdir(self.update_dir)

        self.config = os.path.join(self.ui_root, "active.json")
        self.update_requires = os.path.join(self.update_dir, "requirements.txt")
        self.requirements = {}
        self.check_requirements = True
        self.ui_dir = self.active_dir
        self.git_version = None
        self.root = root
        self.branch = None
        self.update_checker = LoopingCall(self.setup)

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

    def setup(self, branch=None, check_requirements=None, user_specified=None):
        local_ui_path = user_specified or conf.settings.local_ui_path

        self.branch = branch or conf.settings.ui_branch
        self.check_requirements = (check_requirements if check_requirements is not None
                                   else conf.settings.check_ui_requirements)

        # Note that this currently overrides any manual setting of UI.
        # It might be worth considering changing that behavior but the expectation
        # is generally that any manual setting of the UI will happen during development
        # and not for folks checking out the QA / RC builds that bundle the UI.
        if self._check_for_bundled_ui():
            return defer.succeed(True)

        if local_ui_path:
            if os.path.isdir(local_ui_path):
                log.info("Checking user specified UI directory: " + str(local_ui_path))
                self.branch = "user-specified"
                self.loaded_git_version = "user-specified"
                d = self.migrate_ui(source=local_ui_path)
                d.addCallback(lambda _: self._load_ui())
                return d
            else:
                log.info("User specified UI directory doesn't exist, using " + self.branch)
        elif self.loaded_branch == "user-specified":
            log.info("Loading user provided UI")
            d = defer.maybeDeferred(self._load_ui)
            return d
        else:
            log.info("Checking for updates for UI branch: " + self.branch)
            self._git_url = "https://s3.amazonaws.com/lbry-ui/{}/data.json".format(self.branch)
            self._dist_url = "https://s3.amazonaws.com/lbry-ui/{}/dist.zip".format(self.branch)

        d = self._up_to_date()
        d.addCallback(lambda r: self._download_ui() if not r else self._load_ui())
        return d

    def _check_for_bundled_ui(self):
        """Try to load a bundled UI and return True if successful, False otherwise"""
        try:
            bundled_path = get_bundled_ui_path()
        except Exception:
            log.warning('Failed to get path for bundled UI', exc_info=True)
            return False
        else:
            bundle_manager = BundledUIManager(self.root, self.active_dir, bundled_path)
            loaded = bundle_manager.setup()
            if loaded:
                self.loaded_git_version = bundle_manager.version()
            return loaded

    def _up_to_date(self):
        def _get_git_info():
            try:
                # TODO: should this be switched to the non-blocking getPage?
                response = urlopen(self._git_url)
                return defer.succeed(read_sha(response))
            except Exception:
                return defer.fail()

        def _set_git(version):
            self.git_version = version.replace('\n', '')
            if self.git_version == self.loaded_git_version:
                log.info("UI is up to date")
                return defer.succeed(True)
            else:
                log.info("UI updates available, checking if installation meets requirements")
                return defer.succeed(False)

        def _use_existing():
            log.info("Failed to check for new ui version, trying to use cached ui")
            return defer.succeed(True)

        d = _get_git_info()
        d.addCallbacks(_set_git, lambda _: _use_existing)
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

        def _skip_requirements():
            log.info("Skipping ui requirement check")
            return defer.succeed(True)

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
                    log_msg = "Local version %s of %s does not meet UI requirement for version %s"
                    if self.requirements[r]['operator'] == '==':
                        if not self.requirements[r]['version'] == c:
                            passed_requirements = False
                            log.info(log_msg, c, r, self.requirements[r]['version'])
                        else:
                            log.info("Local version of %s meets ui requirement" % r)
                    if self.requirements[r]['operator'] == '>=':
                        if not self.requirements[r]['version'] <= c:
                            passed_requirements = False
                            log.info(log_msg, c, r, self.requirements[r]['version'])
                        else:
                            log.info("Local version of %s meets ui requirement" % r)
                    if self.requirements[r]['operator'] == '<=':
                        if not self.requirements[r]['version'] >= c:
                            passed_requirements = False
                            log.info(log_msg, c, r, self.requirements[r]['version'])
                        else:
                            log.info("Local version of %s meets ui requirement" % r)
            return defer.succeed(passed_requirements)

        def _disp_failure():
            log.info("Failed to satisfy requirements for branch '%s', update was not loaded",
                     self.branch)
            return defer.succeed(False)

        def _do_migrate():
            replace_dir(self.active_dir, source_dir)
            if delete_source:
                shutil.rmtree(source_dir)

            log.info("Loaded UI update")

            f = open(self.config, "w")
            loaded_ui = {
                'commit': self.git_version,
                'branch': self.branch,
                'requirements': self.requirements
            }
            f.write(json.dumps(loaded_ui))
            f.close()

            self.loaded_git_version = loaded_ui['commit']
            self.loaded_branch = loaded_ui['branch']
            self.loaded_requirements = loaded_ui['requirements']
            return defer.succeed(True)

        d = _check_requirements() if self.check_requirements else _skip_requirements()
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
        return load_ui(self.root, self.active_dir)


class BundledUIManager(object):
    """Copies the UI bundled with lbrynet, if available.

    For the QA and nightly builds, we include a copy of the most
    recent checkout of the development UI. For production builds
    nothing is bundled.

    n.b: For QA and nightly builds the update check is skipped.
    """
    def __init__(self, root, active_dir, bundled_ui_path):
        self.root = root
        self.active_dir = active_dir
        self.bundled_ui_path = bundled_ui_path
        self.data_path = os.path.join(bundled_ui_path, 'data.json')
        self._version = None

    def version(self):
        if not self._version:
            self._version = open_and_read_sha(self.data_path)
        return self._version

    def bundle_is_available(self):
        return os.path.exists(self.data_path)

    def setup(self):
        """Load the bundled UI if possible and necessary

        Returns True if there is a bundled UI, False otherwise
        """
        if not self.bundle_is_available():
            log.debug('No bundled UI is available')
            return False
        if not self.is_active_already_bundled_ui():
            replace_dir(self.active_dir, self.bundled_ui_path)
        log.info('Loading the bundled UI')
        load_ui(self.root, self.active_dir)
        return True

    def is_active_already_bundled_ui(self):
        target_data_path = os.path.join(self.active_dir, 'data.json')
        if os.path.exists(target_data_path):
            target_version = open_and_read_sha(target_data_path)
            if self.version() == target_version:
                return True
        return False


def get_bundled_ui_path():
    return pkg_resources.resource_filename('lbrynet', 'resources/ui')


def are_same_version(data_a, data_b):
    """Compare two data files and return True if they are the same version"""
    with open(data_a) as a:
        with open(data_b) as b:
            return read_sha(a) == read_sha(b)


def open_and_read_sha(filename):
    with open(filename) as f:
        return read_sha(f)


def read_sha(filelike):
    data = json.load(filelike)
    return data['sha']


def replace_dir(active_dir, source_dir):
    if os.path.isdir(active_dir):
        shutil.rmtree(active_dir)
    shutil.copytree(source_dir, active_dir)


def load_ui(root, active_dir):
    for name in os.listdir(active_dir):
        entry = os.path.join(active_dir, name)
        if os.path.isdir(entry):
            root.putChild(os.path.basename(entry), NoCacheStaticFile(entry))
