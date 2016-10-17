import logging

from decimal import Decimal
from zope.interface import implements
from twisted.web import server, resource
from twisted.internet import defer
from txjsonrpc import jsonrpclib

from lbrynet.core.Error import InvalidAuthenticationToken, InvalidHeaderError, SubhandlerError
from lbrynet.conf import API_INTERFACE, REFERER, ORIGIN
from lbrynet.lbrynet_daemon.auth.util import APIKey, get_auth_message
from lbrynet.lbrynet_daemon.auth.client import LBRY_SECRET

log = logging.getLogger(__name__)


def default_decimal(obj):
    if isinstance(obj, Decimal):
        return float(obj)


class AuthorizedBase(object):
    def __init__(self):
        self.authorized_functions = []
        self.subhandlers = []
        self.callable_methods = {}

        for methodname in dir(self):
            if methodname.startswith("jsonrpc_"):
                method = getattr(self, methodname)
                self.callable_methods.update({methodname.split("jsonrpc_")[1]: method})
                if hasattr(method, '_auth_required'):
                    self.authorized_functions.append(methodname.split("jsonrpc_")[1])
            elif not methodname.startswith("__"):
                method = getattr(self, methodname)
                if hasattr(method, '_subhandler'):
                    self.subhandlers.append(method)

    @staticmethod
    def auth_required(f):
        f._auth_required = True
        return f

    @staticmethod
    def subhandler(f):
        f._subhandler = True
        return f


class AuthJSONRPCServer(AuthorizedBase):
    """
    Authorized JSONRPC server used as the base class for the LBRY API

    API methods are named with a leading "jsonrpc_"

    Decorators:
        @AuthJSONRPCServer.auth_required: this requires the client include a valid hmac authentication token in their
                                          request

        @AuthJSONRPCServer.subhandler: include the tagged method in the processing of requests, to allow inheriting
                                       classes to modify request handling. Tagged methods will be passed the request
                                       object, and return True when finished to indicate success

    Attributes:
        allowed_during_startup (list): list of api methods that are callable before the server has finished
                                       startup

        sessions (dict): dictionary of active session_id: lbrynet.lbrynet_daemon.auth.util.APIKey values

        authorized_functions (list): list of api methods that require authentication

        subhandlers (list): list of subhandlers

        callable_methods (dict): dictionary of api_callable_name: method values
    """
    implements(resource.IResource)

    isLeaf = True
    OK = 200
    UNAUTHORIZED = 401
    NOT_FOUND = 8001
    FAILURE = 8002

    def __init__(self):
        AuthorizedBase.__init__(self)
        self.allowed_during_startup = []
        self.sessions = {}

    def setup(self):
        return NotImplementedError()

    def render(self, request):
        assert self._check_headers(request), InvalidHeaderError

        session = request.getSession()
        session_id = session.uid

        # if this is a new session, send a new secret and set the expiration, otherwise, session.touch()
        if self._initialize_session(session_id):
            def expire_session():
                self._unregister_user_session(session_id)
            session.startCheckingExpiration()
            session.notifyOnExpire(expire_session)
            message = "OK"
            request.setResponseCode(self.OK)
            self._set_headers(request, message, True)
            self._render_message(request, message)
            return server.NOT_DONE_YET
        session.touch()

        request.content.seek(0, 0)
        content = request.content.read()
        try:
            parsed = jsonrpclib.loads(content)
        except ValueError:
            return server.failure

        function_name = parsed.get('method')
        args = parsed.get('params')
        id = parsed.get('id')
        token = parsed.pop('hmac', None)
        version = self._get_jsonrpc_version(parsed.get('jsonrpc'), id)

        try:
            self._run_subhandlers(request)
        except SubhandlerError:
            return server.failure

        reply_with_next_secret = False
        if function_name in self.authorized_functions:
            try:
                self._verify_token(session_id, parsed, token)
            except InvalidAuthenticationToken:
                log.warning("API validation failed")
                request.setResponseCode(self.UNAUTHORIZED)
                request.finish()
                return server.NOT_DONE_YET
            self._update_session_secret(session_id)
            reply_with_next_secret = True

        try:
            function = self._get_jsonrpc_method(function_name)
        except Exception:
            log.warning("Unknown method: %s", function_name)
            return server.failure

        d = defer.maybeDeferred(function) if args == [{}] else defer.maybeDeferred(function, *args)
        # cancel the response if the connection is broken
        notify_finish = request.notifyFinish()
        notify_finish.addErrback(self._response_failed, d)
        d.addErrback(self._errback_render, id)
        d.addCallback(self._callback_render, request, id, version, reply_with_next_secret)
        d.addErrback(notify_finish.errback)

        return server.NOT_DONE_YET

    def _register_user_session(self, session_id):
        """
        Add or update a HMAC secret for a session

        @param session_id:
        @return: secret
        """
        token = APIKey.new()
        self.sessions.update({session_id: token})
        return token

    def _unregister_user_session(self, session_id):
        log.info("Unregister API session")
        del self.sessions[session_id]

    def _response_failed(self, err, call):
        log.debug(err.getTraceback())

    def _set_headers(self, request, data, update_secret=False):
        request.setHeader("Access-Control-Allow-Origin", API_INTERFACE)
        request.setHeader("Content-Type", "text/json")
        request.setHeader("Content-Length", str(len(data)))
        if update_secret:
            session_id = request.getSession().uid
            request.setHeader(LBRY_SECRET, self.sessions.get(session_id).secret)

    def _render_message(self, request, message):
        request.write(message)
        request.finish()

    def _check_headers(self, request):
        origin = request.getHeader("Origin")
        referer = request.getHeader("Referer")
        if origin not in [None, ORIGIN]:
            log.warning("Attempted api call from %s", origin)
            return False
        if referer is not None and not referer.startswith(REFERER):
            log.warning("Attempted api call from %s", referer)
            return False
        return True

    def _check_function_path(self, function_path):
        if function_path not in self.callable_methods:
            log.warning("Unknown method: %s", function_path)
            return False
        if not self.announced_startup:
            if function_path not in self.allowed_during_startup:
                log.warning("Cannot call %s during startup", function_path)
                return False
        return True

    def _get_jsonrpc_method(self, function_path):
        assert self._check_function_path(function_path)
        return self.callable_methods.get(function_path)

    def _initialize_session(self, session_id):
        if not self.sessions.get(session_id, False):
            log.info("Initializing new api session")
            self.sessions.update({session_id: APIKey.new(seed=session_id, name=session_id)})
            return True
        return False

    def _verify_token(self, session_id, message, token):
        to_auth = get_auth_message(message)
        api_key = self.sessions.get(session_id)
        assert api_key.compare_hmac(to_auth, token), InvalidAuthenticationToken

    def _update_session_secret(self, session_id):
        # log.info("Generating new token for next request")
        self.sessions.update({session_id: APIKey.new(name=session_id)})

    def _get_jsonrpc_version(self, version=None, id=None):
        if version:
            version_for_return = int(float(version))
        elif id and not version:
            version_for_return = jsonrpclib.VERSION_1
        else:
            version_for_return = jsonrpclib.VERSION_PRE1
        return version_for_return

    def _run_subhandlers(self, request):
        for handler in self.subhandlers:
            try:
                assert handler(request)
            except Exception as err:
                log.error(err.message)
                raise SubhandlerError


    def _callback_render(self, result, request, id, version, auth_required=False):
        result_for_return = result if not isinstance(result, dict) else result['result']

        if version == jsonrpclib.VERSION_PRE1:
            if not isinstance(result, jsonrpclib.Fault):
                result_for_return = (result_for_return,)
            # Convert the result (python) to JSON-RPC
        try:
            encoded_message = jsonrpclib.dumps(result_for_return, version=version, default=default_decimal)
            self._set_headers(request, encoded_message, auth_required)
            self._render_message(request, encoded_message)
        except:
            fault = jsonrpclib.Fault(self.FAILURE, "can't serialize output")
            encoded_message = jsonrpclib.dumps(fault, version=version)
            self._set_headers(request, encoded_message)
            self._render_message(request, encoded_message)

    def _errback_render(self, failure, id):
        log.error("Request failed:")
        log.error(failure)
        log.error(failure.value)
        log.error(id)
        if isinstance(failure.value, jsonrpclib.Fault):
            return failure.value
        return server.failure

    def _render_response(self, result, code):
        return defer.succeed({'result': result, 'code': code})


