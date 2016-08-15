import json
import logging
from copy import deepcopy
from lbrynet.conf import CURRENCIES
from distutils.version import StrictVersion
from lbrynet.core.utils import version_is_greater_than

log = logging.getLogger(__name__)

SOURCE_TYPES = ['lbry_sd_hash', 'url', 'btih']
NAME_ALLOWED_CHARSET = 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0987654321-'


def verify_name_characters(name):
    for c in name:
        assert c in NAME_ALLOWED_CHARSET, "Invalid character"
    return True


def skip_validate(value):
    return True


def verify_supported_currency(fee):
    assert len(fee) == 1
    for c in fee:
        assert c in CURRENCIES
    return True


def validate_sources(sources):
    for source in sources:
        assert source in SOURCE_TYPES, "Unknown source type: %s" % str(source)
    return True


def verify_amount(x):
    return isinstance(x, float) and x > 0


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
    versions = None
    migrations = None

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
            self._handle(if_true, rx_value)
        self._handle(if_else, rx_value)

    @cmd(IF_VAL)
    def _if_val(self, rx_value, key, val, if_true, if_else):
        if key in rx_value:
            if rx_value[key] == val:
                self._handle(if_true, rx_value)
        self._handle(if_else, rx_value)

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


class LBCFeeValidator(Validator):
    FV001 = "0.0.1"
    CURRENT_FEE_VERSION = FV001

    FEE_REVISIONS = {}

    FEE_REVISIONS[FV001] = [
        (Validator.REQUIRE, 'amount', verify_amount),
        (Validator.REQUIRE, 'address', skip_validate),
    ]

    FEE_MIGRATIONS = None

    current_version = CURRENT_FEE_VERSION
    versions = FEE_REVISIONS
    migrations = FEE_MIGRATIONS

    def __init__(self, fee):
        Validator.__init__(self, fee)


class BTCFeeValidator(Validator):
    FV001 = "0.0.1"
    CURRENT_FEE_VERSION = FV001

    FEE_REVISIONS = {}

    FEE_REVISIONS[FV001] = [
        (Validator.REQUIRE, 'amount',verify_amount),
        (Validator.REQUIRE, 'address', skip_validate),
    ]

    FEE_MIGRATIONS = None

    current_version = CURRENT_FEE_VERSION
    versions = FEE_REVISIONS
    migrations = FEE_MIGRATIONS

    def __init__(self, fee):
        Validator.__init__(self, fee)


class USDFeeValidator(Validator):
    FV001 = "0.0.1"
    CURRENT_FEE_VERSION = FV001

    FEE_REVISIONS = {}

    FEE_REVISIONS[FV001] = [
        (Validator.REQUIRE, 'amount',verify_amount),
        (Validator.REQUIRE, 'address', skip_validate),
    ]

    FEE_MIGRATIONS = None

    current_version = CURRENT_FEE_VERSION
    versions = FEE_REVISIONS
    migrations = FEE_MIGRATIONS

    def __init__(self, fee):
        Validator.__init__(self, fee)


class LBRYFeeValidator(Validator):
    CV001 = "0.0.1"
    CURRENT_CURRENCY_VERSION = CV001

    CURRENCY_REVISIONS = {}

    CURRENCY_REVISIONS[CV001] = [
        (Validator.OPTIONAL, 'BTC', BTCFeeValidator.validate),
        (Validator.OPTIONAL, 'USD', USDFeeValidator.validate),
        (Validator.OPTIONAL, 'LBC', LBCFeeValidator.validate),
    ]

    CURRENCY_MIGRATIONS = None

    current_version = CURRENT_CURRENCY_VERSION
    versions = CURRENCY_REVISIONS
    migrations = CURRENCY_MIGRATIONS

    def __init__(self, fee_dict):
        Validator.__init__(self, fee_dict)
        self.currency_symbol = self.keys()[0]
        self.amount = self._get_amount()
        self.address = self[self.currency_symbol]['address']

    def _get_amount(self):
        amt = self[self.currency_symbol]['amount']
        if isinstance(amt, float):
            return amt
        else:
            try:
                return float(amt)
            except TypeError:
                log.error('Failed to convert %s to float', amt)
                raise


class Metadata(Validator):
    MV001 = "0.0.1"
    MV002 = "0.0.2"
    MV003 = "0.0.3"
    CURRENT_METADATA_VERSION = MV003

    METADATA_REVISIONS = {}

    METADATA_REVISIONS[MV001] = [
        (Validator.REQUIRE, 'title', skip_validate),
        (Validator.REQUIRE, 'description', skip_validate),
        (Validator.REQUIRE, 'author', skip_validate),
        (Validator.REQUIRE, 'language', skip_validate),
        (Validator.REQUIRE, 'license', skip_validate),
        (Validator.REQUIRE, 'content-type', skip_validate),
        (Validator.REQUIRE, 'sources', validate_sources),
        (Validator.OPTIONAL, 'thumbnail', skip_validate),
        (Validator.OPTIONAL, 'preview', skip_validate),
        (Validator.OPTIONAL, 'fee', verify_supported_currency),
        (Validator.OPTIONAL, 'contact', skip_validate),
        (Validator.OPTIONAL, 'pubkey', skip_validate),
    ]

    METADATA_REVISIONS[MV002] = [
        (Validator.REQUIRE, 'nsfw', skip_validate),
        (Validator.REQUIRE, 'ver', skip_validate),
        (Validator.OPTIONAL, 'license_url', skip_validate),
    ]

    METADATA_REVISIONS[MV003] = [
        (Validator.REQUIRE, 'content_type', skip_validate),
        (Validator.SKIP, 'content-type'),
        (Validator.OPTIONAL, 'sig', skip_validate),
        (Validator.IF_KEY, 'sig', (Validator.REQUIRE, 'pubkey', skip_validate), Validator.DO_NOTHING),
        (Validator.IF_KEY, 'pubkey', (Validator.REQUIRE, 'sig', skip_validate), Validator.DO_NOTHING),
    ]

    MIGRATE_MV001_TO_MV002 = [
        (Validator.IF_KEY, 'nsfw', Validator.DO_NOTHING, (Validator.LOAD, 'nsfw', False)),
        (Validator.IF_KEY, 'ver', Validator.DO_NOTHING, (Validator.LOAD, 'ver', MV002)),
    ]

    MIGRATE_MV002_TO_MV003 = [
        (Validator.IF_VAL, 'ver', MV002, (Validator.UPDATE, 'content-type', 'content_type'), Validator.DO_NOTHING),
        (Validator.IF_VAL, 'ver', MV002, (Validator.LOAD, 'ver', MV003), Validator.DO_NOTHING),
    ]

    METADATA_MIGRATIONS = [
        MIGRATE_MV001_TO_MV002,
        MIGRATE_MV002_TO_MV003,
    ]

    current_version = CURRENT_METADATA_VERSION
    versions = METADATA_REVISIONS
    migrations = METADATA_MIGRATIONS

    def __init__(self, metadata, process_now=True):
        Validator.__init__(self, metadata, process_now)
        self.meta_version = self.get('ver', Metadata.MV001)
        self._load_fee()

    def _load_fee(self):
        if 'fee' in self:
            self.update({'fee': LBRYFeeValidator(self['fee'])})

