import logging
import os
from zope.interface import implements, implementer
from twisted.cred import portal, checkers, credentials, error as cred_error
from twisted.internet import defer
from twisted.web import resource
from lbrynet.lbrynet_daemon.auth.util import load_api_keys, APIKey, API_KEY_NAME, save_api_keys
from lbrynet.lbrynet_daemon.LBRYDaemon import log_dir as DATA_DIR

log = logging.getLogger(__name__)


# initialize api key if none exist
if not os.path.isfile(os.path.join(DATA_DIR, ".api_keys")):
    keys = {}
    api_key = APIKey.new()
    api_key.rename(API_KEY_NAME)
    keys.update(api_key)
    save_api_keys(keys, os.path.join(DATA_DIR, ".api_keys"))


@implementer(portal.IRealm)
class HttpPasswordRealm:
    def __init__(self, resource):
        self.resource = resource

    def requestAvatar(self, avatarId, mind, *interfaces):
        log.info("Processing request for %s", avatarId)
        if resource.IResource in interfaces:
            return (resource.IResource, self.resource, lambda: None)
        raise NotImplementedError()


class PasswordChecker:
    implements(checkers.ICredentialsChecker)
    credentialInterfaces = (credentials.IUsernamePassword,)

    def __init__(self):
        keys = load_api_keys(os.path.join(DATA_DIR, ".api_keys"))
        self.passwords = {key: keys[key]['token'] for key in keys}

    def requestAvatarId(self, creds):
        if creds.username in self.passwords:
            pw = self.passwords.get(creds.username)
            pw_match = creds.checkPassword(pw)
            if pw_match is True:
                return defer.succeed(creds.username)
        log.warning('Incorrect username or password')
        return defer.fail(cred_error.UnauthorizedLogin('Incorrect username or password'))

