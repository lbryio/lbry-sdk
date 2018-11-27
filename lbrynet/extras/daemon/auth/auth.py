import logging
from zope.interface import implementer
from twisted.cred import portal, checkers, credentials, error as cred_error
from twisted.internet import defer
from twisted.web import resource
from lbrynet.extras.daemon.auth.keyring import Keyring

log = logging.getLogger(__name__)


@implementer(portal.IRealm)
class HttpPasswordRealm:
    def __init__(self, resource):
        self.resource = resource

    def requestAvatar(self, avatarId, mind, *interfaces):
        log.debug("Processing request for %s", avatarId)
        if resource.IResource in interfaces:
            return (resource.IResource, self.resource, lambda: None)
        raise NotImplementedError()


@implementer(checkers.ICredentialsChecker)
class PasswordChecker:
    credentialInterfaces = (credentials.IUsernamePassword,)

    def __init__(self, keyring: Keyring):
        self.api_key = keyring.api_key

    def requestAvatarId(self, creds):
        if creds.checkPassword(self.api_key.secret.encode()) and creds.username == self.api_key.name.encode():
            return defer.succeed(creds.username)
        log.warning('Incorrect username or password')
        return defer.fail(cred_error.UnauthorizedLogin('Incorrect username or password'))
