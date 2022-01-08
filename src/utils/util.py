import json
import logging
import socket
import sys
import uuid
from threading import Timer


def broadcast(port, broadcast_message):

    broadcast_message["msg_uuid"] = str(uuid.uuid4())

    # Create a UDP socket
    broadcast_socket = socket.socket(
        socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP
    )
    # TODO On linux we need to do reuseport on windows reuseaddr
    if sys.platform == "win32":
        broadcast_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    else:
        broadcast_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
    broadcast_socket.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    broadcast_socket.sendto(
        str.encode(json.dumps(broadcast_message)), ("<broadcast>", port)
    )
    broadcast_socket.close()


class CustomLogger(logging.getLoggerClass()):
    def __init__(self, name, level=logging.INFO):
        super().__init__(name)
        self.setLevel(level)


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
