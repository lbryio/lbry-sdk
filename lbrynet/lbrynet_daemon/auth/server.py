import logging

from decimal import Decimal
from twisted.web import server
from twisted.internet import defer
from txjsonrpc import jsonrpclib
from txjsonrpc.web import jsonrpc
from txjsonrpc.web.jsonrpc import Handler

from lbrynet.core.Error import InvalidAuthenticationToken, InvalidHeaderError
from lbrynet.lbrynet_daemon.auth.util import APIKey
from lbrynet.lbrynet_daemon.auth.client import LBRY_SECRET
from lbrynet.conf import ALLOWED_DURING_STARTUP

log = logging.getLogger(__name__)


def default_decimal(obj):
    if isinstance(obj, Decimal):
        return float(obj)


def authorizer(cls):
    cls.authorized_functions = []
    for methodname in dir(cls):
        if methodname.startswith("jsonrpc_"):
            method = getattr(cls, methodname)
            if hasattr(method, '_auth_required'):
                cls.authorized_functions.append(methodname.split("jsonrpc_")[1])
    return cls


def auth_required(f):
    f._auth_required = True
    return f


@authorizer
class LBRYJSONRPCServer(jsonrpc.JSONRPC):

    isLeaf = True

    def __init__(self):
        jsonrpc.JSONRPC.__init__(self)
        self.sessions = {}

    def _register_user_session(self, session_id):
        token = APIKey.new()
        self.sessions.update({session_id: token})
        return token

    def _responseFailed(self, err, call):
        log.debug(err.getTraceback())

    def _set_headers(self, request, data):
        request.setHeader("Access-Control-Allow-Origin", "localhost")
        request.setHeader("Content-Type", "text/json")
        request.setHeader("Content-Length", str(len(data)))

    def _render_message(self, request, message):
        request.write(message)
        request.finish()

    def _check_headers(self, request):
        origin = request.getHeader("Origin")
        referer = request.getHeader("Referer")

        if origin not in [None, 'http://localhost:5279']:
            log.warning("Attempted api call from %s", origin)
            raise InvalidHeaderError

        if referer is not None and not referer.startswith('http://localhost:5279/'):
            log.warning("Attempted api call from %s", referer)
            raise InvalidHeaderError

    def _handle(self, request):
        def _check_function_path(function_path):
            if not self.announced_startup:
                if function_path not in ALLOWED_DURING_STARTUP:
                    log.warning("Cannot call %s during startup", function_path)
                    raise Exception("Function not allowed")

        def _get_function(function_path):
            function = self._getFunction(function_path)
            return function

        def _verify_token(session_id, message, token):
            request.setHeader(LBRY_SECRET, "")
            api_key = self.sessions.get(session_id, None)
            assert api_key is not None, InvalidAuthenticationToken
            r = api_key.compare_hmac(message, token)
            assert r, InvalidAuthenticationToken
            # log.info("Generating new token for next request")
            self.sessions.update({session_id: APIKey.new(name=session_id)})
            request.setHeader(LBRY_SECRET, self.sessions.get(session_id).secret)

        session = request.getSession()
        session_id = session.uid
        session_store = self.sessions.get(session_id, False)

        if not session_store:
            token = APIKey.new(seed=session_id, name=session_id)
            log.info("Initializing new api session")
            self.sessions.update({session_id: token})
            # log.info("Generated token %s", str(self.sessions[session_id]))

        request.content.seek(0, 0)
        content = request.content.read()

        parsed = jsonrpclib.loads(content)

        functionPath = parsed.get("method")

        _check_function_path(functionPath)
        require_auth = functionPath in self.authorized_functions
        if require_auth:
            token = parsed.pop('hmac')
            to_auth = functionPath.encode('hex') + str(parsed.get('id')).encode('hex')
            _verify_token(session_id, to_auth.decode('hex'), token)

        args = parsed.get('params')
        id = parsed.get('id')
        version = parsed.get('jsonrpc')

        if version:
            version = int(float(version))
        elif id and not version:
            version = jsonrpclib.VERSION_1
        else:
            version = jsonrpclib.VERSION_PRE1

        if self.wallet_type == "lbryum" and functionPath in ['set_miner', 'get_miner_status']:
            log.warning("Mining commands are not available in lbryum")
            raise Exception("Command not available in lbryum")

        try:
            function = _get_function(functionPath)
            if args == [{}]:
                d = defer.maybeDeferred(function)
            else:
                d = defer.maybeDeferred(function, *args)
        except jsonrpclib.Fault as f:
            d = self._cbRender(f, request, id, version)
        finally:
            # cancel the response if the connection is broken
            notify_finish = request.notifyFinish()
            notify_finish.addErrback(self._responseFailed, d)
            d.addErrback(self._ebRender, id)
            d.addCallback(self._cbRender, request, id, version)
            d.addErrback(notify_finish.errback)

    def _cbRender(self, result, request, id, version):
        if isinstance(result, Handler):
            result = result.result

        if isinstance(result, dict):
            result = result['result']

        if version == jsonrpclib.VERSION_PRE1:
            if not isinstance(result, jsonrpclib.Fault):
                result = (result,)
            # Convert the result (python) to JSON-RPC
        try:
            s = jsonrpclib.dumps(result, version=version, default=default_decimal)
            self._render_message(request, s)
        except:
            f = jsonrpclib.Fault(self.FAILURE, "can't serialize output")
            s = jsonrpclib.dumps(f, version=version)
            self._set_headers(request, s)
            self._render_message(request, s)

    def _ebRender(self, failure, id):
        log.error(failure)
        log.error(failure.value)
        log.error(id)
        if isinstance(failure.value, jsonrpclib.Fault):
            return failure.value
        return server.failure

    def render(self, request):
        try:
            self._check_headers(request)
        except InvalidHeaderError:
            return server.failure

        try:
            self._handle(request)
        except:
            return server.failure

        return server.NOT_DONE_YET

    def _render_response(self, result, code):
        return defer.succeed({'result': result, 'code': code})


