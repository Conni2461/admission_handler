import socket
from threading import Thread, Timer


class Invokeable:
    def __init__(self, signal, *args, **kwargs):
        self._signal = signal
        self._args = args
        self._kwargs = kwargs

    @property
    def signal(self):
        return self._signal

    @property
    def kwargs(self):
        return self._kwargs

class SocketThread(Thread):
    def __init__(self, queue):
        super().__init__()
        self.stopped = False
        self._queue = queue

    def emit(self, **kwargs):
        signal = kwargs.pop("signal")
        self._queue.put(Invokeable(signal, **kwargs))

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

def get_real_ip():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.connect(('1.1.1.1', 1))
    return sock.getsockname()[0]
