import logging

from twisted.web import server, guard, resource
from twisted.cred import portal

from lbrynet import conf
from lbrynet.extras.daemon.auth.auth import PasswordChecker, HttpPasswordRealm
from lbrynet.extras.daemon.auth.keyring import Keyring

log = logging.getLogger(__name__)


class HTTPJSONRPCFactory(server.Site):
    def __init__(self, resource, keyring, requestFactory=None, *args, **kwargs):
        super().__init__(resource, requestFactory=requestFactory, *args, **kwargs)
        self.use_ssl = False


class HTTPSJSONRPCFactory(server.Site):
    def __init__(self, resource, keyring, requestFactory=None, *args, **kwargs):
        super().__init__(resource, requestFactory=requestFactory, *args, **kwargs)
        self.options = keyring.private_certificate.options()
        self.use_ssl = True


class AuthJSONRPCResource(resource.Resource):
    def __init__(self, protocol):
        resource.Resource.__init__(self)
        self.putChild(b"", protocol)
        self.putChild(conf.settings['API_ADDRESS'].encode(), protocol)

    def getChild(self, name, request):
        request.setHeader('cache-control', 'no-cache, no-store, must-revalidate')
        request.setHeader('expires', '0')
        return self if name == '' else resource.Resource.getChild(self, name, request)

    def getServerFactory(self, keyring: Keyring, use_authentication: bool, use_https: bool) -> server.Site:
        factory_class = HTTPSJSONRPCFactory if use_https else HTTPJSONRPCFactory
        if use_authentication:
            log.info("Using authenticated API")
            checker = PasswordChecker(keyring)
            realm = HttpPasswordRealm(self)
            portal_to_realm = portal.Portal(realm, [checker, ])
            root = guard.HTTPAuthSessionWrapper(
                portal_to_realm, [guard.BasicCredentialFactory('Login to lbrynet api'), ]
            )
        else:
            log.info("Using non-authenticated API")
            root = self
        return factory_class(root, keyring)
