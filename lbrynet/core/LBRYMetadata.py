import json

BASE_METADATA_FIELDS = ['title', 'description', 'author', 'language', 'license', 'content-type']
OPTIONAL_METADATA_FIELDS = ['thumbnail', 'preview', 'fee', 'contact', 'pubkey']

#v0.0.1 metadata
METADATA_REVISIONS = {'0.0.1': {'required': BASE_METADATA_FIELDS, 'optional': OPTIONAL_METADATA_FIELDS}}

#v0.0.2 metadata additions
METADATA_REVISIONS['0.0.2'] = {'required': ['nsfw'], 'optional': []}


class Metadata(dict):
    def __init__(self, metadata):
        dict.__init__(self)
        self.metaversion = None
        m = metadata.copy()
        for version in METADATA_REVISIONS:
            for k in METADATA_REVISIONS[version]['required']:
                assert k in metadata, "Missing required metadata field: %s" % k
                self.update({k: m.pop(k)})
            for k in METADATA_REVISIONS[version]['optional']:
                if k in metadata:
                    self.update({k: m.pop(k)})
            if not len(m):
                self.metaversion = version
                break
        assert m == {}, "Unknown metadata keys: %s" % json.dumps(m.keys())