import asyncio
import logging
from six.moves.urllib import parse as urlparse
import json
import inspect
import signal

from functools import wraps
from twisted.web import server
from twisted.internet import defer
from twisted.internet.defer import Deferred
from twisted.python.failure import Failure
from twisted.internet.error import ConnectionDone, ConnectionLost
from txjsonrpc import jsonrpclib
from traceback import format_exc

from lbrynet import conf, analytics
from lbrynet.core.Error import InvalidAuthenticationToken
from lbrynet.core import utils
from lbrynet.core.Error import ComponentsNotStarted, ComponentStartConditionNotMet
from lbrynet.core.looping_call_manager import LoopingCallManager
from lbrynet.daemon.ComponentManager import ComponentManager
from .keyring import APIKey, Keyring
from .undecorated import undecorated
from .factory import AuthJSONRPCResource
from lbrynet.daemon.json_response_encoder import JSONResponseEncoder
log = logging.getLogger(__name__)

EMPTY_PARAMS = [{}]
LBRY_SECRET = "LBRY_SECRET"


class JSONRPCError:
    # http://www.jsonrpc.org/specification#error_object
    CODE_PARSE_ERROR = -32700  # Invalid JSON. Error while parsing the JSON text.
    CODE_INVALID_REQUEST = -32600  # The JSON sent is not a valid Request object.
    CODE_METHOD_NOT_FOUND = -32601  # The method does not exist / is not available.
    CODE_INVALID_PARAMS = -32602  # Invalid method parameter(s).
    CODE_INTERNAL_ERROR = -32603  # Internal JSON-RPC error (I think this is like a 500?)
    CODE_APPLICATION_ERROR = -32500  # Generic error with our app??
    CODE_AUTHENTICATION_ERROR = -32501  # Authentication failed

    MESSAGES = {
        CODE_PARSE_ERROR: "Parse Error. Data is not valid JSON.",
        CODE_INVALID_REQUEST: "JSON data is not a valid Request",
        CODE_METHOD_NOT_FOUND: "Method Not Found",
        CODE_INVALID_PARAMS: "Invalid Params",
        CODE_INTERNAL_ERROR: "Internal Error",
        CODE_AUTHENTICATION_ERROR: "Authentication Failed",
    }

    HTTP_CODES = {
        CODE_INVALID_REQUEST: 400,
        CODE_PARSE_ERROR: 400,
        CODE_INVALID_PARAMS: 400,
        CODE_METHOD_NOT_FOUND: 404,
        CODE_INTERNAL_ERROR: 500,
        CODE_APPLICATION_ERROR: 500,
        CODE_AUTHENTICATION_ERROR: 401,
    }

    def __init__(self, message, code=CODE_APPLICATION_ERROR, traceback=None, data=None):
        assert isinstance(code, int), "'code' must be an int"
        assert (data is None or isinstance(data, dict)), "'data' must be None or a dict"
        self.code = code
        if message is None:
            message = self.MESSAGES[code] if code in self.MESSAGES else "API Error"
        self.message = message
        self.data = {} if data is None else data
        self.traceback = []
        if traceback is not None:
            trace_lines = traceback.split("\n")
            for i, t in enumerate(trace_lines):
                if "--- <exception caught here> ---" in t:
                    if len(trace_lines) > i + 1:
                        self.traceback = [j for j in trace_lines[i+1:] if j]
                        break

    def to_dict(self):
        return {
            'code': self.code,
            'message': self.message,
            'data': self.traceback
        }

    @classmethod
    def create_from_exception(cls, message, code=CODE_APPLICATION_ERROR, traceback=None):
        return cls(message, code=code, traceback=traceback)


class UnknownAPIMethodError(Exception):
    pass


def trap(err, *to_trap):
    err.trap(*to_trap)


def jsonrpc_dumps_pretty(obj, **kwargs):
    try:
        id_ = kwargs.pop("id")
    except KeyError:
        id_ = None

    if isinstance(obj, JSONRPCError):
        data = {"jsonrpc": "2.0", "error": obj.to_dict(), "id": id_}
    else:
        data = {"jsonrpc": "2.0", "result": obj, "id": id_}

    return json.dumps(data, cls=JSONResponseEncoder, sort_keys=True, indent=2, **kwargs) + "\n"


class JSONRPCServerType(type):
    def __new__(mcs, name, bases, newattrs):
        klass = type.__new__(mcs, name, bases, newattrs)
        klass.callable_methods = {}
        klass.deprecated_methods = {}

        for methodname in dir(klass):
            if methodname.startswith("jsonrpc_"):
                method = getattr(klass, methodname)
                if not hasattr(method, '_deprecated'):
                    klass.callable_methods.update({methodname.split("jsonrpc_")[1]: method})
                else:
                    klass.deprecated_methods.update({methodname.split("jsonrpc_")[1]: method})
        return klass


class AuthorizedBase(metaclass=JSONRPCServerType):

    @staticmethod
    def deprecated(new_command=None):
        def _deprecated_wrapper(f):
            f.new_command = new_command
            f._deprecated = True
            return f
        return _deprecated_wrapper

    @staticmethod
    def requires(*components, **conditions):
        if conditions and ["conditions"] != list(conditions.keys()):
            raise SyntaxError("invalid conditions argument")
        condition_names = conditions.get("conditions", [])

        def _wrap(fn):
            @wraps(fn)
            def _inner(*args, **kwargs):
                component_manager = args[0].component_manager
                for condition_name in condition_names:
                    condition_result, err_msg = component_manager.evaluate_condition(condition_name)
                    if not condition_result:
                        raise ComponentStartConditionNotMet(err_msg)
                if not component_manager.all_components_running(*components):
                    raise ComponentsNotStarted("the following required components have not yet started: "
                                               "%s" % json.dumps(components))
                return fn(*args, **kwargs)
            return _inner
        return _wrap


class AuthJSONRPCServer(AuthorizedBase):
    """
    Authorized JSONRPC server used as the base class for the LBRY API

    API methods are named with a leading "jsonrpc_"

    Attributes:
        sessions (dict): (dict): {<session id>: <lbrynet.daemon.auth.util.APIKey>}
        callable_methods (dict): {<api method name>: <api method>}

    Authentication:
        If use_authentication is true, basic HTTP and HMAC authentication will be used for all requests and the
        service url will require a username and password.

        To start an authenticated session a client sends an HTTP POST to <user>:<password>@<api host>:<api port>.
        If accepted, the server replies with a TWISTED_SESSION cookie containing a session id and the message "OK".
        The client initializes their shared secret for hmac to be the b64 encoded sha256 of their session id.

        To send an authenticated request a client sends an HTTP POST to the auth api url with the TWISTED_SESSION
        cookie and includes a hmac token in the message using the previously set shared secret. If the token is valid
        the server will randomize the shared secret and return the new value under the LBRY_SECRET header, which the
        client uses to generate the token for their next request.
    """
    #implements(resource.IResource)

    isLeaf = True
    allowed_during_startup = []
    component_attributes = {}

    def __init__(self, analytics_manager=None, component_manager=None, use_authentication=None, use_https=None,
                 to_skip=None, looping_calls=None, reactor=None):
        if not reactor:
            from twisted.internet import reactor
        self.analytics_manager = analytics_manager or analytics.Manager.new_instance()
        self.component_manager = component_manager or ComponentManager(
            analytics_manager=self.analytics_manager,
            skip_components=to_skip or [],
            reactor=reactor
        )
        self.looping_call_manager = LoopingCallManager({n: lc for n, (lc, t) in (looping_calls or {}).items()})
        self._looping_call_times = {n: t for n, (lc, t) in (looping_calls or {}).items()}
        self._use_authentication = use_authentication or conf.settings['use_auth_http']
        self._use_https = use_https or conf.settings['use_https']
        self.listening_port = None
        self._component_setup_deferred = None
        self.announced_startup = False
        self.sessions = {}
        self.server = None
        self.keyring = Keyring.generate_and_save()

    @defer.inlineCallbacks
    def start_listening(self):
        from twisted.internet import reactor, error as tx_error

        try:
            self.server = self.get_server_factory()
            if self.server.use_ssl:
                log.info("Using SSL")
                self.listening_port = reactor.listenSSL(
                    conf.settings['api_port'], self.server, self.server.options, interface=conf.settings['api_host']
                )
            else:
                log.info("Not using SSL")
                self.listening_port = reactor.listenTCP(
                    conf.settings['api_port'], self.server, interface=conf.settings['api_host']
                )
            log.info("lbrynet API listening on TCP %s:%i", conf.settings['api_host'], conf.settings['api_port'])
            yield self.setup()
            self.analytics_manager.send_server_startup_success()
        except tx_error.CannotListenError:
            log.error('lbrynet API failed to bind TCP %s:%i for listening. Daemon is already running or this port is '
                      'already in use by another application.', conf.settings['api_host'], conf.settings['api_port'])
            reactor.fireSystemEvent("shutdown")
        except defer.CancelledError:
            log.info("shutting down before finished starting")
            reactor.fireSystemEvent("shutdown")
        except Exception as err:
            self.analytics_manager.send_server_startup_error(str(err))
            log.exception('Failed to start lbrynet-daemon')
            reactor.fireSystemEvent("shutdown")

    def setup(self):
        from twisted.internet import reactor

        reactor.addSystemEventTrigger('before', 'shutdown', self._shutdown)
        if not self.analytics_manager.is_started:
            self.analytics_manager.start()
        self.analytics_manager.send_server_startup()
        for lc_name, lc_time in self._looping_call_times.items():
            self.looping_call_manager.start(lc_name, lc_time)

        def update_attribute(setup_result, component):
            setattr(self, self.component_attributes[component.component_name], component.component)

        kwargs = {component: update_attribute for component in self.component_attributes.keys()}
        self._component_setup_deferred = self.component_manager.setup(**kwargs)
        return self._component_setup_deferred

    @staticmethod
    def _already_shutting_down(sig_num, frame):
        log.info("Already shutting down")

    def _shutdown(self):
        # ignore INT/TERM signals once shutdown has started
        signal.signal(signal.SIGINT, self._already_shutting_down)
        signal.signal(signal.SIGTERM, self._already_shutting_down)
        if self.listening_port:
            self.listening_port.stopListening()
        self.looping_call_manager.shutdown()
        if self.server is not None:
            for session in list(self.server.sessions.values()):
                session.expire()
        if self.analytics_manager:
            self.analytics_manager.shutdown()
        try:
            self._component_setup_deferred.cancel()
        except (AttributeError, defer.CancelledError):
            pass
        if self.component_manager is not None:
            d = self.component_manager.stop()
            d.addErrback(log.fail(), 'Failure while shutting down')
        else:
            d = defer.succeed(None)
        return d

    def get_server_factory(self):
        return AuthJSONRPCResource(self).getServerFactory(self.keyring, self._use_authentication, self._use_https)

    def _set_headers(self, request, data, update_secret=False):
        if conf.settings['allowed_origin']:
            request.setHeader("Access-Control-Allow-Origin", conf.settings['allowed_origin'])
        request.setHeader("Content-Type", "application/json")
        request.setHeader("Accept", "application/json-rpc")
        request.setHeader("Content-Length", str(len(data)))
        if update_secret:
            session_id = request.getSession().uid
            request.setHeader(LBRY_SECRET, self.sessions.get(session_id).secret)

    @staticmethod
    def _render_message(request, message: str):
        request.write(message.encode())
        request.finish()

    def _render_error(self, failure, request, id_):
        if isinstance(failure, JSONRPCError):
            error = failure
        elif isinstance(failure, Failure):
            # maybe failure is JSONRPCError wrapped in a twisted Failure
            error = failure.check(JSONRPCError)
            if error is None:
                # maybe its a twisted Failure with another type of error
                if hasattr(failure.type, "code"):
                    error_code = failure.type.code
                else:
                    error_code = JSONRPCError.CODE_APPLICATION_ERROR
                error = JSONRPCError.create_from_exception(
                    failure.getErrorMessage() or failure.type.__name__,
                    code=error_code,
                    traceback=failure.getTraceback()
                )
            if not failure.check(ComponentsNotStarted, ComponentStartConditionNotMet):
                log.warning("error processing api request: %s\ntraceback: %s", error.message,
                            "\n".join(error.traceback))
        else:
            # last resort, just cast it as a string
            error = JSONRPCError(str(failure))

        response_content = jsonrpc_dumps_pretty(error, id=id_, ledger=self.ledger)
        self._set_headers(request, response_content)
        request.setResponseCode(200)
        self._render_message(request, response_content)

    @staticmethod
    def _handle_dropped_request(result, d, function_name):
        if not d.called:
            log.warning("Cancelling dropped api request %s", function_name)
            d.cancel()

    def render(self, request):
        try:
            return self._render(request)
        except BaseException as e:
            log.error(e)
            error = JSONRPCError.create_from_exception(str(e), traceback=format_exc())
            self._render_error(error, request, None)
            return server.NOT_DONE_YET

    def _render(self, request):
        time_in = utils.now()
        # if not self._check_headers(request):
        #     self._render_error(Failure(InvalidHeaderError()), request, None)
        #     return server.NOT_DONE_YET
        session = request.getSession()
        session_id = session.uid
        finished_deferred = request.notifyFinish()

        if self._use_authentication:
            # if this is a new session, send a new secret and set the expiration
            # otherwise, session.touch()
            if self._initialize_session(session_id):
                def expire_session():
                    self._unregister_user_session(session_id)

                session.notifyOnExpire(expire_session)
                message = "OK"
                request.setResponseCode(200)
                self._set_headers(request, message, True)
                self._render_message(request, message)
                return server.NOT_DONE_YET
            else:
                session.touch()

        request.content.seek(0, 0)
        content = request.content.read().decode()
        try:
            parsed = jsonrpclib.loads(content)
        except json.JSONDecodeError:
            log.warning("Unable to decode request json")
            self._render_error(JSONRPCError(None, code=JSONRPCError.CODE_PARSE_ERROR), request, None)
            return server.NOT_DONE_YET

        request_id = None
        try:
            function_name = parsed.get('method')
            args = parsed.get('params', {})
            request_id = parsed.get('id', None)
            token = parsed.pop('hmac', None)
        except AttributeError as err:
            log.warning(err)
            self._render_error(
                JSONRPCError(None, code=JSONRPCError.CODE_INVALID_REQUEST), request, request_id
            )
            return server.NOT_DONE_YET

        reply_with_next_secret = False
        if self._use_authentication:
            try:
                self._verify_token(session_id, parsed, token)
            except InvalidAuthenticationToken as err:
                log.warning("API validation failed")
                self._render_error(
                    JSONRPCError.create_from_exception(
                        str(err),
                        code=JSONRPCError.CODE_AUTHENTICATION_ERROR,
                        traceback=format_exc()
                    ),
                    request, request_id
                )
                return server.NOT_DONE_YET
            request.addCookie("TWISTED_SESSION", session_id)
            self._update_session_secret(session_id)
            reply_with_next_secret = True

        try:
            fn = self._get_jsonrpc_method(function_name)
        except UnknownAPIMethodError as err:
            log.warning('Failed to get function %s: %s', function_name, err)
            self._render_error(
                JSONRPCError(None, code=JSONRPCError.CODE_METHOD_NOT_FOUND),
                request, request_id
            )
            return server.NOT_DONE_YET

        if args in (EMPTY_PARAMS, []):
            _args, _kwargs = (), {}
        elif isinstance(args, dict):
            _args, _kwargs = (), args
        elif len(args) == 1 and isinstance(args[0], dict):
            # TODO: this is for backwards compatibility. Remove this once API and UI are updated
            # TODO: also delete EMPTY_PARAMS then
            _args, _kwargs = (), args[0]
        elif len(args) == 2 and isinstance(args[0], list) and isinstance(args[1], dict):
            _args, _kwargs = args
        else:
            raise ValueError('invalid args format')

        params_error, erroneous_params = self._check_params(fn, _args, _kwargs)
        if params_error is not None:
            params_error_message = '{} for {} command: {}'.format(
                params_error, function_name, ', '.join(erroneous_params)
            )
            log.warning(params_error_message)
            self._render_error(
                JSONRPCError(params_error_message, code=JSONRPCError.CODE_INVALID_PARAMS),
                request, request_id
            )
            return server.NOT_DONE_YET

        try:
            result = fn(self, *_args, **_kwargs)
            if isinstance(result, Deferred):
                d = result
            elif isinstance(result, Failure):
                d = defer.fail(result)
            elif asyncio.iscoroutine(result):
                d = Deferred.fromFuture(asyncio.ensure_future(result))
            else:
                d = defer.succeed(result)
        except:
            d = defer.fail(Failure(captureVars=Deferred.debug))

        # finished_deferred will callback when the request is finished
        # and errback if something went wrong. If the errback is
        # called, cancel the deferred stack. This is to prevent
        # request.finish() from being called on a closed request.
        finished_deferred.addErrback(self._handle_dropped_request, d, function_name)

        d.addCallback(self._callback_render, request, request_id, reply_with_next_secret)
        d.addErrback(trap, ConnectionDone, ConnectionLost, defer.CancelledError)
        d.addErrback(self._render_error, request, request_id)
        d.addBoth(lambda _: log.debug("%s took %f",
                                      function_name,
                                      (utils.now() - time_in).total_seconds()))
        return server.NOT_DONE_YET

    def _register_user_session(self, session_id):
        """
        Add or update a HMAC secret for a session

        @param session_id:
        @return: secret
        """
        log.info("Started new api session")
        token = APIKey.create(seed=session_id)
        self.sessions.update({session_id: token})

    def _unregister_user_session(self, session_id):
        log.info("Unregister API session")
        del self.sessions[session_id]

    def _check_headers(self, request):
        return (
            self._check_header_source(request, 'Origin') and
            self._check_header_source(request, 'Referer')
        )

    def _check_header_source(self, request, header):
        """Check if the source of the request is allowed based on the header value."""
        source = request.getHeader(header)
        if not self._check_source_of_request(source):
            log.warning("Attempted api call from invalid %s: %s", header, source)
            return False
        return True

    def _check_source_of_request(self, source):
        if source is None:
            return True
        if conf.settings['api_host'] == '0.0.0.0':
            return True
        server, port = self.get_server_port(source)
        return self._check_server_port(server, port)

    def _check_server_port(self, server, port):
        api = (conf.settings['api_host'], conf.settings['api_port'])
        return (server, port) == api or self._is_from_allowed_origin(server, port)

    def _is_from_allowed_origin(self, server, port):
        allowed_origin = conf.settings['allowed_origin']
        if not allowed_origin:
            return False
        if allowed_origin == '*':
            return True
        allowed_server, allowed_port = self.get_server_port(allowed_origin)
        return (allowed_server, allowed_port) == (server, port)

    def get_server_port(self, origin):
        parsed = urlparse.urlparse(origin)
        server_port = parsed.netloc.split(':')
        assert len(server_port) <= 2
        if len(server_port) == 2:
            return server_port[0], int(server_port[1])
        else:
            return server_port[0], 80

    def _verify_method_is_callable(self, function_path):
        if function_path not in self.callable_methods:
            raise UnknownAPIMethodError(function_path)

    def _get_jsonrpc_method(self, function_path):
        if function_path in self.deprecated_methods:
            new_command = self.deprecated_methods[function_path].new_command
            log.warning('API function \"%s\" is deprecated, please update to use \"%s\"',
                        function_path, new_command)
            function_path = new_command
        self._verify_method_is_callable(function_path)
        return self.callable_methods.get(function_path)

    @staticmethod
    def _check_params(function, args_tup, args_dict):
        argspec = inspect.getfullargspec(undecorated(function))
        num_optional_params = 0 if argspec.defaults is None else len(argspec.defaults)

        duplicate_params = [
            duplicate_param
            for duplicate_param in argspec.args[1:len(args_tup) + 1]
            if duplicate_param in args_dict
        ]

        if duplicate_params:
            return 'Duplicate parameters', duplicate_params

        missing_required_params = [
            required_param
            for required_param in argspec.args[len(args_tup)+1:-num_optional_params]
            if required_param not in args_dict
        ]
        if len(missing_required_params):
            return 'Missing required parameters', missing_required_params

        extraneous_params = [] if argspec.varkw is not None else [
            extra_param
            for extra_param in args_dict
            if extra_param not in argspec.args[1:]
        ]
        if len(extraneous_params):
            return 'Extraneous parameters', extraneous_params

        return None, None

    def _initialize_session(self, session_id):
        if not self.sessions.get(session_id):
            self._register_user_session(session_id)
            return True
        return False

    def _verify_token(self, session_id, message, token):
        if token is None:
            raise InvalidAuthenticationToken('Authentication token not found')
        to_auth = json.dumps(message, sort_keys=True)
        api_key = self.sessions.get(session_id)
        if not api_key.compare_hmac(to_auth, token):
            raise InvalidAuthenticationToken('Invalid authentication token')

    def _update_session_secret(self, session_id):
        self.sessions.update({session_id: APIKey.create(name=session_id)})

    def _callback_render(self, result, request, id_, auth_required=False):
        try:
            message = jsonrpc_dumps_pretty(result, id=id_, ledger=self.ledger)
            request.setResponseCode(200)
            self._set_headers(request, message, auth_required)
            self._render_message(request, message)
        except Exception as err:
            log.exception("Failed to render API response: %s", result)
            self._render_error(err, request, id_)

    @staticmethod
    def _render_response(result):
        return defer.succeed(result)
