class IncompleteResponse(Exception):
    """
    Raised by reflector server when client sends a portion of a json request,
    used buffering the incoming request
    """


class ReflectorClientVersionError(Exception):
    """
    Raised by reflector server if client sends an incompatible or unknown version
    """


class ReflectorRequestError(Exception):
    """
    Raised by reflector server if client sends a message without the required fields
    """


class ReflectorRequestDecodeError(Exception):
    """
    Raised by reflector server if client sends an invalid json request
    """
