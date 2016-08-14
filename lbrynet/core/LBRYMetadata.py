import json
import logging
from copy import deepcopy
from lbrynet.conf import CURRENCIES
from distutils.version import StrictVersion

log = logging.getLogger(__name__)

SOURCE_TYPES = ['lbry_sd_hash', 'url', 'btih']
NAME_ALLOWED_CHARSET = 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0987654321-'


def verify_name_characters(name):
    for c in name:
        assert c in NAME_ALLOWED_CHARSET, "Invalid character"
    return True


def skip_validate(value):
    pass


def verify_supported_currency(fee):
    assert len(fee) == 1
    for c in fee:
        assert c in CURRENCIES


def validate_sources(sources):
    for source in sources:
        assert source in SOURCE_TYPES, "Unknown source type"


class Validator(dict):
    """
    Base class for validated dictionaries
    """

    DO_NOTHING = "pass"
    UPDATE = "update_key"
    IF_KEY = "if_key_exists"
    REQUIRE = "require"
    SKIP = "skip"
    OPTIONAL = "add_optional"
    ADD = "add"
    IF_VAL = "if_val"
    SUPERSEDE = "supersede"

    # override these
    current_version = None
    versions = None
    migrations = None
    supersessions = None

    @classmethod
    def load_from_hex(cls, hex_val):
        return cls(json.loads(hex_val.decode('hex')))

    def process(self):
        unprocessed = deepcopy(self)
        if self.migrations is not None:
            self._migrate_value(unprocessed)

    def serialize(self):
        return json.dumps(self).encode("hex")

    def as_json(self):
        return json.dumps(self)

    def __init__(self, value, process_now=True):
        dict.__init__(self)
        self._skip = []
        value_to_load = deepcopy(value)
        if self.supersessions is not None:
            self._run_supersessions(value_to_load)
        self._verify_value(value_to_load)
        self._raw = deepcopy(self)
        self.version = self.get('ver', "0.0.1")
        if process_now:
            self.process()

    def _handle(self, cmd_tpl, value):
        if cmd_tpl == self.DO_NOTHING:
            return

        cmd = cmd_tpl[0]

        if cmd == self.IF_KEY:
            key, on_key, on_else = cmd_tpl[1:]
            if key in value:
                return self._handle(on_key, value)
            elif on_else:
                return self._handle(on_else, value)
            return

        elif cmd == self.IF_VAL:
            key, v, on_val, on_else = cmd_tpl[1:]
            if key not in value:
                return self._handle(on_else, value)
            if value[key] == v:
                return self._handle(on_val, value)
            elif on_else:
                return self._handle(on_else, value)
            return

        elif cmd == self.UPDATE:
            old_key, new_key = cmd_tpl[1:]
            value.update({new_key: value.pop(old_key)})

        elif cmd == self.REQUIRE:
            required, validator = cmd_tpl[1:]
            if required not in self._skip:
                assert required in value if required not in self else True, "Missing required field: %s, %s" % (required, self.as_json())
                if required not in self._skip and required in value:
                    self.update({required: value.pop(required)})
                    validator(self[required])
            else:
                pass

        elif cmd == self.OPTIONAL:
            optional, validator = cmd_tpl[1:]
            if optional in value and optional not in self._skip:
                self.update({optional: value.pop(optional)})
                validator(self[optional])
            else:
                pass

        elif cmd == self.SKIP:
            to_skip = cmd_tpl[1]
            self._skip.append(to_skip)

        elif cmd == self.ADD:
            key, pushed_val = cmd_tpl[1:]
            self.update({key: pushed_val})

        elif cmd == self.SUPERSEDE:
            ver = cmd_tpl[1]
            self.update({'ver': ver})
            self.version = ver

    def _load_revision(self, version, value):
        for k in self.versions[version]:
            self._handle(k, value)

    def _verify_value(self, value):
        for version in sorted(self.versions, key=StrictVersion):
            self._load_revision(version, value)
            if not value:
                self['ver'] = version
                break
        for skip in self._skip:
            if skip in value:
                value.pop(skip)
        assert value == {}, "Unknown keys: %s, %s" % (json.dumps(value.keys()), self.as_json())

    def _migrate_value(self, value):
        for migration in self.migrations:
            self._run_migration(migration, value)

    def _run_migration(self, commands, value):
        for cmd in commands:
            self._handle(cmd, value)

    def _run_supersessions(self, value):
        for cmd in self.supersessions:
            self._handle(cmd, value)


class LBCFeeValidator(Validator):
    FV001 = "0.0.1"
    CURRENT_FEE_VERSION = FV001

    FEE_REVISIONS = {}

    FEE_REVISIONS[FV001] = [
        (Validator.REQUIRE, 'amount', skip_validate),
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
        (Validator.REQUIRE, 'amount', skip_validate),
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
        (Validator.REQUIRE, 'amount', skip_validate),
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
        (Validator.OPTIONAL, 'BTC', BTCFeeValidator),
        (Validator.OPTIONAL, 'USD', USDFeeValidator),
        (Validator.OPTIONAL, 'LBC', LBCFeeValidator),
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
        (Validator.IF_KEY, 'nsfw', Validator.DO_NOTHING, (Validator.ADD, 'nsfw', False)),
        (Validator.IF_KEY, 'ver', Validator.DO_NOTHING, (Validator.SUPERSEDE, MV002)),
    ]
    MIGRATE_MV002_TO_MV003 = [
        (Validator.IF_KEY, 'content_type', Validator.DO_NOTHING, (Validator.UPDATE, 'content-type', 'content_type')),
        (Validator.IF_KEY, 'ver', Validator.DO_NOTHING, (Validator.SUPERSEDE, MV003)),
        (Validator.IF_VAL, 'ver', MV002, (Validator.SUPERSEDE, MV003), Validator.DO_NOTHING),
    ]

    METADATA_MIGRATIONS = [
        MIGRATE_MV001_TO_MV002,
        MIGRATE_MV002_TO_MV003,
    ]

    SUPERSESSIONS = [
        (Validator.SKIP, 'content-type'),
    ]

    current_version = CURRENT_METADATA_VERSION
    versions = METADATA_REVISIONS
    migrations = METADATA_MIGRATIONS
    supersessions = SUPERSESSIONS

    def __init__(self, metadata):
        Validator.__init__(self, metadata)
        self.meta_version = self.get('ver', Metadata.MV001)
        self._load_fee()

    def _load_fee(self):
        if 'fee' in self:
            self.update({'fee': LBRYFeeValidator(self['fee'])})