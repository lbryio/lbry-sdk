import asyncio
from functools import wraps

REFLECTOR_V1 = 0
REFLECTOR_V2 = 1


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


class IncompleteResponse(Exception):
    """
    Raised by reflector server when client sends a portion of a json request,
    used buffering the incoming request
    """


def reflector_factory(task_factory):
    @wraps(task_factory)
    def base_protocol(loop, coro):
        next_task = asyncio.tasks.Task(coro, loop=loop)
        current_task = asyncio.Task.current_task(loop=loop)
        previous_task = getattr(current_task, 'current_task', None)
        setattr(next_task, 'current_task', previous_task)
    return base_protocol
