import os
from contextlib import contextmanager


@contextmanager
def get_read_handle(path):
    """
    Get os independent read handle for a file
    """

    if os.name == "nt":
        file_mode = 'rb'
    else:
        file_mode = 'r'
    read_handle = open(path, file_mode)
    yield read_handle
    read_handle.close()
