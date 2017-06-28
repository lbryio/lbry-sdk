import logging
from zope.interface import implementer
from twisted.cred import portal, checkers, credentials, error as cred_error
from twisted.internet import defer
from twisted.web import resource
from lbrynet.daemon.auth.util import load_api_keys

log = logging.getLogger(__name__)


@implementer(portal.IRealm)
class HttpPasswordRealm(object):
    def __init__(self, resource):
        self.resource = resource

    def requestAvatar(self, avatarId, mind, *interfaces):
        log.debug("Processing request for %s", avatarId)
        if resource.IResource in interfaces:
            return (resource.IResource, self.resource, lambda: None)
        raise NotImplementedError()


@implementer(checkers.ICredentialsChecker)
class PasswordChecker(object):
    credentialInterfaces = (credentials.IUsernamePassword,)

    def __init__(self, passwords):
        self.passwords = passwords

    @classmethod
    def load_file(cls, key_path):
        keys = load_api_keys(key_path)
        return cls.load(keys)

    @classmethod
    def load(cls, password_dict):
        passwords = {key: password_dict[key].secret for key in password_dict}
        return cls(passwords)

    def requestAvatarId(self, creds):
        if creds.username in self.passwords:
            pw = self.passwords.get(creds.username)
            pw_match = creds.checkPassword(pw)
            if pw_match:
                return defer.succeed(creds.username)
        log.warning('Incorrect username or password')
        return defer.fail(cred_error.UnauthorizedLogin('Incorrect username or password'))

