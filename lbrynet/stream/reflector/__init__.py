import asyncio
import functools
from lbrynet.conf import Config


def auto_reflector(storage, streams_to_re_reflect):

    @functools.wraps(auto_reflector, storage)
    class Reflect(storage):
        queue = asyncio.Queue()

        def get_task_factory(self):
            try:
                yield self.queue.join
                task = self.queue.get_nowait()
                await asyncio.get_running_loop().create_task(task).add_done_callback(self.queue.task_done)
                assert self.queue.empty()
            except StopAsyncIteration:
                yield self.queue
            finally:
                yield self.queue.join

        def set_task(self):
            try:
                task = self.queue.get_nowait()
                await asyncio.get_running_loop().create_task(task).add_done_callback(self.queue.task_done)
                assert task.done(), self.queue.put_nowait(task)
            except (asyncio.QueueFull, asyncio.QueueEmpty) as exc:
                raise exc.with_traceback(self.queue)
            return

        def crontab(self, config: Config):
            self.__init__(storage.get_streams_to_re_reflect)
            asyncio.sleep(config.auto_re_reflect_interval)

        def __init__(self, streams: streams_to_re_reflect):
            self.queue.put_nowait(*streams)
            self.get_task_factory()

        def __aenter__(self):
            return self.__anext__()

        def __aexit__(self, exc_type, exc_val, exc_tb):
            return lambda: exc_type, exc_val, exc_tb

        def __await__(self):
            return self.set_task()

        def __anext__(self):
            return self.get_task_factory()

        def __aiter__(self):
            return self
    return Reflect


__doc__ = """Reflector is a protocol to re-host lbry blobs and streams.

API Reference:

    Client sends a version handshake: {'version': int,}
        - Client has successfully established connection and may continue

    Client must send a stream descriptor request:
        + {'sd_blob_hash': str, 'sd_blob_size': int}
    
    Client may begin the file transfer of the sd blob if send_sd_blob was True.

    If the Client sends the blob:
        Server indicates if the transfer was successful: {'received_sd_blob': bool,}
    If the transfer was not successful:
        blob is added to the needed_blobs queue.

Server API Reference:
    - Server replies with the same version: +{'version': int,}
        - If the Server has a validated copy of the sd blob:
            * The response will include the needed_blobs field.
        - If the Server does not have the sd blob:
            * The needed_blobs field will not be included.
        - If the Server is not aware of the sd blobs missing:
            * The response will not include needed_blobs.
    + {'send_sd_blob': bool, 'needed_blobs': list, conditional}


TCP/IP Reference:
                            REFLECTOR, 5566

+=============[CLIENT]===========+  +=============[SERVER]===========+
[      FRAME      |    STATE     ]  [      FRAME      |    STATE     ]
|-----------------+--------------|  |-----------------+--------------|
| connection_made | ESTABLISHED  |  | connection_made | ESTABLISHED  |
| connection_lost |   CLOSING    |  | connection_lost |   CLOSING    |
| send_request    | SYN          |  | send_response   | ACK-SEND     |
| data_received   | SYN-RECEIVED |  | data_received   | SYN-RECEIVED |
| send_handshake  | SYN-SEND     |  | handle_request  | SYN-ACK      |
| send_blob       | SYN-SEND     |  +================================+
| send_descriptor | SYN-SEND     |           ReflectorServer TCB
| failed_upload   | SEND-CLOSING |
+================================+
        ReflectorClient TCB

"""
