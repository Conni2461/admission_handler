from threading import Thread, Timer


class SocketThread(Thread):
    def __init__(self, *args, **kwargs):
        super().__init__()
        self.stopped = False

    def join(self):
        self.stopped = True
        super().join()

    def start(self):
        self.stopped = False
        super().start()

class CircularList(list):
    def __init__(self, *args):
        super().__init__(*args)
        self.i = 0

    def next(self, index=None):
        if index is not None:
            self.i = index
        if (self.i + 1) <= (len(self) - 1):
            self.i += 1
        else:
            self.i = 0
        return self[self.i]


class RepeatTimer(Timer):
    def run(self):
        while not self.finished.wait(self.interval):
            self.function(*self.args, **self.kwargs)
