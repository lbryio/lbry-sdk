# Copyright (c) 2017, Neil Booth
#
# All rights reserved.
#
# See the file "LICENCE" for information about the copyright
# and warranty status of this software.

'''Class for server environment configuration and defaults.'''


from os import environ

from torba.server.util import class_logger


class EnvBase(object):
    '''Wraps environment configuration.'''

    class Error(Exception):
        pass

    def __init__(self):
        self.logger = class_logger(__name__, self.__class__.__name__)
        self.allow_root = self.boolean('ALLOW_ROOT', False)
        self.host = self.default('HOST', 'localhost')
        self.rpc_host = self.default('RPC_HOST', 'localhost')
        self.loop_policy = self.event_loop_policy()

    @classmethod
    def default(cls, envvar, default):
        return environ.get(envvar, default)

    @classmethod
    def boolean(cls, envvar, default):
        default = 'Yes' if default else ''
        return bool(cls.default(envvar, default).strip())

    @classmethod
    def required(cls, envvar):
        value = environ.get(envvar)
        if value is None:
            raise cls.Error('required envvar {} not set'.format(envvar))
        return value

    @classmethod
    def integer(cls, envvar, default):
        value = environ.get(envvar)
        if value is None:
            return default
        try:
            return int(value)
        except Exception:
            raise cls.Error('cannot convert envvar {} value {} to an integer'
                            .format(envvar, value))

    @classmethod
    def custom(cls, envvar, default, parse):
        value = environ.get(envvar)
        if value is None:
            return default
        try:
            return parse(value)
        except Exception as e:
            raise cls.Error('cannot parse envvar {} value {}'
                            .format(envvar, value)) from e

    @classmethod
    def obsolete(cls, envvars):
        bad = [envvar for envvar in envvars if environ.get(envvar)]
        if bad:
            raise cls.Error('remove obsolete environment variables {}'
                            .format(bad))

    def event_loop_policy(self):
        policy = self.default('EVENT_LOOP_POLICY', None)
        if policy is None:
            return None
        if policy == 'uvloop':
            import uvloop
            return uvloop.EventLoopPolicy()
        raise self.Error('unknown event loop policy "{}"'.format(policy))

    def cs_host(self, *, for_rpc):
        '''Returns the 'host' argument to pass to asyncio's create_server
        call.  The result can be a single host name string, a list of
        host name strings, or an empty string to bind to all interfaces.

        If rpc is True the host to use for the RPC server is returned.
        Otherwise the host to use for SSL/TCP servers is returned.
        '''
        host = self.rpc_host if for_rpc else self.host
        result = [part.strip() for part in host.split(',')]
        if len(result) == 1:
            result = result[0]
        # An empty result indicates all interfaces, which we do not
        # permitted for an RPC server.
        if for_rpc and not result:
            result = 'localhost'
        return result
