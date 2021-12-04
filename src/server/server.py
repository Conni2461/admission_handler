import socket
import sys
import uuid
import json
from threading import Thread

from louie import dispatcher

from ..utils.constants import (
    BROADCAST_PORT,
    BUFFER_SIZE,
    IDENT_SERVER,
    MAX_TRIES,
    TIMEOUT,
    State,
)
from ..utils.signals import ON_BROADCAST_MESSAGE
from ..utils.util import broadcast, CustomLogger

import logging


class TCPListener:
    def __init__(self, timeout=TIMEOUT):
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._socket.bind(("", 0))
        socketname = self._socket.getsockname()
        self._address = socketname[0]
        self._port = socketname[1]
        self._socket.settimeout(timeout)
        self._open = True

    @property
    def port(self):
        return self._port

    @property
    def address(self):
        return self._address

    def reset_timeout(self):
        self._socket.settimeout()

    def set_timeout(self, value):
        self._socket.settimeout(value)

    def listen(self):
        try:
            data, address = self._socket.recvfrom(BUFFER_SIZE)
            return data, address
        except socket.timeout:
            return None, None

    def __del__(self):
        self.close()

    def close(self):
        if self._open:
            self._open = False
            self._socket.close()


class UDPListener(Thread):
    def __init__(self):
        super().__init__()
        self.listen_socket = socket.socket(
            socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP
        )
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
            data, addr = self.listen_socket.recvfrom(BUFFER_SIZE)
            if data:
                dispatcher.send(
                    signal=ON_BROADCAST_MESSAGE,
                    sender=self,
                    data=data.decode(),
                    addr=addr,
                )


class Server:
    def __init__(self):
        # TODO: Broadcast message that he wants to join
        # TODO:   - When nobody answers create new server group with itself as a leader
        # TODO:   - Leader needs to update group view
        self._state = State.PENDING
        self._tcp = TCPListener()
        self._uuid = uuid.uuid4()

        self._logger = CustomLogger("Server")

        mes = {
            "intention": IDENT_SERVER,
            "uuid": "{}".format(self._uuid),
            "address": self._tcp.address,
            "port": self._tcp.port,
        }

        broadcast(BROADCAST_PORT, json.dumps(mes))
        for _ in range(MAX_TRIES):
            res, add = self._tcp.listen()
            if res is not None:
                self._state = State.MEMBER
                break

        self._group_view = dict()
        if self._state == State.PENDING:
            self._state = State.LEADER
            self._group_view[self._uuid] = (self._tcp.address, self._tcp.port)

        print(f"{self._state}, {self._group_view}")
        self._udp_listener = UDPListener()
        self._udp_listener.start()

        dispatcher.connect(
            self.on_udp_msg, signal=ON_BROADCAST_MESSAGE, sender=self._udp_listener
        )

    def on_udp_msg(self, data=None, addr=None):
        if self._state == State.LEADER:
            print(data)
        print("Received broadcast message:", data, addr)

    def run(self):
        while True:
            pass
