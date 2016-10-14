import jsonschema
import logging

from jsonschema import ValidationError

log = logging.getLogger(__name__)


class StructuredDict(dict):
    """
    A dictionary that enforces a structure specified by a schema, and supports
    migration between different versions of the schema.
    """

    # To be specified in sub-classes, an array in the format
    # [(version, schema, migration), ...]
    _versions = []

    # Used internally to allow schema lookups by version number
    _schemas = {}

    version = None

    def __init__(self, value, starting_version, migrate=True, target_version=None):
        dict.__init__(self, value)

        self.version = starting_version
        self._schemas = dict([(version, schema) for (version, schema, _) in self._versions])

        self.validate(starting_version)

        if migrate:
            self.migrate(target_version)

    def validate(self, version):
        jsonschema.validate(self, self._schemas[version])

    def migrate(self, target_version=None):
        if target_version:
            assert self._versions.index(target_version) > self.versions.index(self.version), "Current version is above target version"

        above_starting_version = False
        for version, schema, migration in self._versions:
            if not above_starting_version:
                if version == self.version:
                    above_starting_version = True
                continue

            migration()
            try:
                self.validate(version)
            except ValidationError as e:
                raise ValidationError, "Could not migrate to version %s due to validation error: %s" % (version, e.message)

            self.version = version
            if target_version and version == target_version:
                break
