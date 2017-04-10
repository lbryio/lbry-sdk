#!/usr/bin/env python
#
# This library is free software, distributed under the terms of
# the GNU Lesser General Public License Version 3, or any later version.
# See the COPYING file included in this archive
#
# The docstrings in this module contain epytext markup; API documentation
# may be created by processing this file with epydoc: http://epydoc.sf.net

import hashlib
import random
from lbrynet.core.utils import generate_id

class Message(object):
    """ Base class for messages - all "unknown" messages use this class """

    def __init__(self, rpcID, nodeID):
        self.id = rpcID
        self.nodeID = nodeID


class RequestMessage(Message):
    """ Message containing an RPC request """

    def __init__(self, nodeID, method, methodArgs, rpcID=None):
        if rpcID == None:
            rpcID = generate_id()
        Message.__init__(self, rpcID, nodeID)
        self.request = method
        self.args = methodArgs


class ResponseMessage(Message):
    """ Message containing the result from a successful RPC request """

    def __init__(self, rpcID, nodeID, response):
        Message.__init__(self, rpcID, nodeID)
        self.response = response


class ErrorMessage(ResponseMessage):
    """ Message containing the error from an unsuccessful RPC request """

    def __init__(self, rpcID, nodeID, exceptionType, errorMessage):
        ResponseMessage.__init__(self, rpcID, nodeID, errorMessage)
        if isinstance(exceptionType, type):
            self.exceptionType = '%s.%s' % (exceptionType.__module__, exceptionType.__name__)
        else:
            self.exceptionType = exceptionType
