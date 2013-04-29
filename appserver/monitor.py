from twisted.internet import task


IN_CREATE = 0x00000100L         # Subfile was created
IN_DELETE = 0x00000200L         # Subfile was delete


class NotWatchingError(KeyError):
    pass


class _Watcher(object):
    def __init__(self, reactor, directory, interval):
        self.directory = directory
        self.current = set(directory.children())
        self.clock = task.LoopingCall(self._tick)
        self.clock.clock = reactor
        self.interval = interval
        self.callbacks = []

    def _tick(self):
        children = set(self.directory.children())
        added = children - self.current
        removed = self.current - children
        self.current = children

        for child in added:
            self._event(child, IN_CREATE)

        for child in removed:
            self._event(child, IN_DELETE)

    def _event(self, path, event_mask):
        for mask, callbacks in self.callbacks:
            if event_mask & mask:
                for callback in callbacks:
                    callback(path, event_mask)

    def addCallbacks(self, callbacks, mask):
        self.callbacks.append((mask, callbacks))

    def start(self):
        self.clock.start(self.interval, now=False)

    def stop(self):
        self.clock.stop()


class DirectoryMonitor(object):
    # NOTE: This may be replaced by twisted.internet.inotify at some
    # point. Currently, our needs don't justify the added burden of
    # development/testing under linux.

    interval = 1

    def __init__(self, reactor):
        self._reactor = reactor
        self._watchers = {}

    def watch(self, directory, callbacks, mask=IN_CREATE|IN_DELETE):
        try:
            watcher = self._watchers[directory.path]
        except KeyError:
            watcher = _Watcher(self._reactor, directory, self.interval)
            self._watchers[directory.path] = watcher
            watcher.start()

        watcher.addCallbacks(callbacks, mask)

    def ignore(self, directory):
        key = directory.path
        if key not in self._watchers:
            raise NotWatchingError()
        self._watchers.pop(key).stop()
