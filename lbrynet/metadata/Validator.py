import json
import logging
from copy import deepcopy
from distutils.version import StrictVersion
from lbrynet.core.utils import version_is_greater_than

log = logging.getLogger(__name__)


def skip_validate(value):
    return True


def processor(cls):
    for methodname in dir(cls):
        method = getattr(cls, methodname)
        if hasattr(method, 'cmd_name'):
            cls.commands.update({method.cmd_name: methodname})
    return cls


def cmd(cmd_name):
    def wrapper(func):
        func.cmd_name = cmd_name
        return func
    return wrapper


@processor
class Validator(dict):
    """
    Base class for validated dictionaries
    """

    # override these
    current_version = None
    versions = {}
    migrations = []

    # built in commands
    DO_NOTHING = "do_nothing"
    UPDATE = "update_key"
    IF_KEY = "if_key"
    REQUIRE = "require"
    SKIP = "skip"
    OPTIONAL = "optional"
    LOAD = "load"
    IF_VAL = "if_val"

    commands = {}

    @classmethod
    def load_from_hex(cls, hex_val):
        return cls(json.loads(hex_val.decode('hex')))

    @classmethod
    def validate(cls, value):
        if cls(value):
            return True
        else:
            return False

    def __init__(self, value, process_now=False):
        dict.__init__(self)
        self._skip = []
        value_to_load = deepcopy(value)
        if process_now:
            self.process(value_to_load)
        self._verify_value(value_to_load)
        self.version = self.get('ver', "0.0.1")

    def process(self, value):
        if self.migrations is not None:
            self._migrate_value(value)

    @cmd(DO_NOTHING)
    def _do_nothing(self):
        pass

    @cmd(SKIP)
    def _add_to_skipped(self, rx_value, key):
        if key not in self._skip:
            self._skip.append(key)

    @cmd(UPDATE)
    def _update(self, rx_value, old_key, new_key):
        rx_value.update({new_key: rx_value.pop(old_key)})

    @cmd(IF_KEY)
    def _if_key(self, rx_value, key, if_true, if_else):
        if key in rx_value:
            return self._handle(if_true, rx_value)
        return self._handle(if_else, rx_value)

    @cmd(IF_VAL)
    def _if_val(self, rx_value, key, val, if_true, if_else):
        if key in rx_value:
            if rx_value[key] == val:
                return self._handle(if_true, rx_value)
        return self._handle(if_else, rx_value)

    @cmd(LOAD)
    def _load(self, rx_value, key, value):
        rx_value.update({key: value})

    @cmd(REQUIRE)
    def _require(self, rx_value, key, validator=None):
        if key not in self._skip:
            assert key in rx_value, "Key is missing: %s" % key
            if isinstance(validator, type):
                assert isinstance(rx_value[key], validator), "%s: %s isn't required %s" % (key, type(rx_value[key]), validator)
            elif callable(validator):
                assert validator(rx_value[key]), "Failed to validate %s" % key
            self.update({key: rx_value.pop(key)})

    @cmd(OPTIONAL)
    def _optional(self, rx_value, key, validator=None):
        if key in rx_value and key not in self._skip:
            if isinstance(validator, type):
                assert isinstance(rx_value[key], validator), "%s type %s isn't required %s" % (key, type(rx_value[key]), validator)
            elif callable(validator):
                assert validator(rx_value[key]), "Failed to validate %s" % key
            self.update({key: rx_value.pop(key)})

    def _handle(self, cmd_tpl, value):
        if cmd_tpl == Validator.DO_NOTHING:
            return
        command = cmd_tpl[0]
        f = getattr(self, self.commands[command])
        if len(cmd_tpl) > 1:
            args = (value,) + cmd_tpl[1:]
            f(*args)
        else:
            f()

    def _load_revision(self, version, value):
        for k in self.versions[version]:
            self._handle(k, value)

    def _verify_value(self, value):
        val_ver = value.get('ver', "0.0.1")
        # verify version requirements in reverse order starting from the version asserted in the value
        versions = sorted([v for v in self.versions if not version_is_greater_than(v, val_ver)], key=StrictVersion, reverse=True)
        for version in versions:
            self._load_revision(version, value)
        assert value == {} or value.keys() == self._skip, "Unknown keys: %s" % json.dumps(value)

    def _migrate_value(self, value):
        for migration in self.migrations:
            self._run_migration(migration, value)

    def _run_migration(self, commands, value):
        for cmd in commands:
            self._handle(cmd, value)

