from asyncio import Event, get_running_loop


class TaskGroup:

    def __init__(self, loop=None):
        self._loop = loop or get_running_loop()
        self._tasks = set()
        self.done = Event()
        self.started = Event()

    def __len__(self):
        return len(self._tasks)

    def add(self, coro):
        task = self._loop.create_task(coro)
        self._tasks.add(task)
        self.started.set()
        self.done.clear()
        task.add_done_callback(self._remove)
        return task

    def _remove(self, task):
        self._tasks.remove(task)
        if len(self._tasks) < 1:
            self.done.set()
            self.started.clear()

    def cancel(self):
        for task in self._tasks:
            task.cancel()
        self.done.set()
        self.started.clear()
