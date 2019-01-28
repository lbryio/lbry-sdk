import asyncio
import typing

from lbrynet.conf import Config

if typing.TYPE_CHECKING:
    from lbrynet.stream.stream_manager import StreamManager


class AutoReflector(StreamManager):
    """
    Async iterator that every interval re-reflects streams.
    """
    def auto_reflector(self) -> typing.AsyncIterator:
        await asyncio.sleep(Config.auto_re_reflect_interval)
        host, port = self.reflector_servers
        async for index, stream in self.storage.get_streams_to_re_reflect():
            loop = asyncio.new_event_loop()
            loop.create_task(stream.upload_to_reflector(stream, host, port))
            while divmod(index, 10):
                yield from loop.run_in_executor(self, func=self.reflect_streams)
        return asyncio.get_event_loop().call_at(Config.auto_re_reflect_interval, callback=self.auto_reflector)
