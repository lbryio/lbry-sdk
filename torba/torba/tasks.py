from asyncio import Event, get_event_loop


class TaskGroup:

    def __init__(self, loop=None):
        self._loop = loop or get_event_loop()
        self._tasks = set()
        self.done = Event()

    def add(self, coro):
        task = self._loop.create_task(coro)
        self._tasks.add(task)
        self.done.clear()
        task.add_done_callback(self._remove)
        return task

    def _remove(self, task):
        self._tasks.remove(task)
        len(self._tasks) < 1 and self.done.set()

    def cancel(self):
        for task in self._tasks:
            task.cancel()
