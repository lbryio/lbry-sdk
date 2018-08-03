import logging
import os

from twisted.web import server, guard, resource
from twisted.cred import portal

from lbrynet import conf
from .auth import PasswordChecker, HttpPasswordRealm
from .util import initialize_api_key_file

log = logging.getLogger(__name__)


class AuthJSONRPCResource(resource.Resource):
    def __init__(self, protocol):
        resource.Resource.__init__(self)
        self.putChild("", protocol)
        self.putChild(conf.settings['API_ADDRESS'], protocol)

    def getChild(self, name, request):
        request.setHeader('cache-control', 'no-cache, no-store, must-revalidate')
        request.setHeader('expires', '0')
        return self if name == '' else resource.Resource.getChild(self, name, request)

    def getServerFactory(self):
        if conf.settings['use_auth_http']:
            log.info("Using authenticated API")
            pw_path = os.path.join(conf.settings['data_dir'], ".api_keys")
            initialize_api_key_file(pw_path)
            checker = PasswordChecker.load_file(pw_path)
            realm = HttpPasswordRealm(self)
            portal_to_realm = portal.Portal(realm, [checker, ])
            factory = guard.BasicCredentialFactory('Login to lbrynet api')
            root = guard.HTTPAuthSessionWrapper(portal_to_realm, [factory, ])
        else:
            log.info("Using non-authenticated API")
            root = self
        return server.Site(root)
