import socket
import sys
from threading import Thread

from louie import dispatcher

from ..utils.constants import BROADCAST_PORT
from ..utils.signals import ON_BROADCAST_MESSAGE


class Listener(Thread):
    def __init__(self):
        super().__init__()
        self.listen_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        # Set the socket to broadcast and enable reusing addresses
        if sys.platform == "win32":
            self.listen_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        else:
            self.listen_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        self.listen_socket.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        # Bind socket to address and port
        self.listen_socket.bind(("", BROADCAST_PORT))

    def run(self):
        print("Listening to broadcast messages")
        while True:
            data, addr = self.listen_socket.recvfrom(1024)
            if data:
                dispatcher.send(signal=ON_BROADCAST_MESSAGE, sender=self, data=data.decode(), addr=addr)

class Server:
    def __init__(self):
        self._listener = Listener()
        self._listener.start()

        dispatcher.connect(self.on_udp_msg, signal=ON_BROADCAST_MESSAGE, sender=self._listener)

    def on_udp_msg(self, data=None, addr=None):
        print("Received broadcast message:", data, addr)

    def run(self):
        while True:
            pass
