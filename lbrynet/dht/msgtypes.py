#!/usr/bin/env python
#
# This library is free software, distributed under the terms of
# the GNU Lesser General Public License Version 3, or any later version.
# See the COPYING file included in this archive
#
# The docstrings in this module contain epytext markup; API documentation
# may be created by processing this file with epydoc: http://epydoc.sf.net

from lbrynet.core.utils import generate_id
from . import constants


class Message:
    """ Base class for messages - all "unknown" messages use this class """

    def __init__(self, rpcID, nodeID):
        if len(rpcID) != constants.rpc_id_length:
            raise ValueError("invalid rpc id: %i bytes (expected 20)" % len(rpcID))
        if len(nodeID) != constants.key_bits // 8:
            raise ValueError("invalid node id: %i bytes (expected 48)" % len(nodeID))
        self.id = rpcID
        self.nodeID = nodeID


class RequestMessage(Message):
    """ Message containing an RPC request """

    def __init__(self, nodeID, method, methodArgs, rpcID=None):
        if rpcID is None:
            rpcID = generate_id()[:constants.rpc_id_length]
        super().__init__(rpcID, nodeID)
        self.request = method
        self.args = methodArgs


class ResponseMessage(Message):
    """ Message containing the result from a successful RPC request """

    def __init__(self, rpcID, nodeID, response):
        super().__init__(rpcID, nodeID)
        self.response = response


class ErrorMessage(ResponseMessage):
    """ Message containing the error from an unsuccessful RPC request """

    def __init__(self, rpcID, nodeID, exceptionType, errorMessage):
        super().__init__(rpcID, nodeID, errorMessage)
        if isinstance(exceptionType, type):
            exceptionType = ('%s.%s' % (exceptionType.__module__, exceptionType.__name__)).encode()
        self.exceptionType = exceptionType
