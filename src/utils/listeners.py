import uuid
import json
import logging
import socket
import struct
import sys
from collections import deque
from threading import Thread

from louie import dispatcher

from .constants import (
    BROADCAST_PORT,
    MULTICAST_IP,
    MULTICAST_PORT,
    BUFFER_SIZE,
    MAX_MSG_BUFF_SIZE,
    TIMEOUT,
)
from .signals import ON_BROADCAST_MESSAGE, ON_MULTICAST_MESSAGE, ON_TCP_MESSAGE


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

class TCPListener(SocketThread):
    def __init__(self, timeout=TIMEOUT):
        super().__init__()
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._socket.bind(("", 0))
        socketname = self._socket.getsockname()
        self._address = socketname[0]
        self._port = socketname[1]
        self._socket.settimeout(timeout)
        self._open = True

        self._logger = logging.getLogger(f"TCPListener")
        self._logger.setLevel(logging.DEBUG)
        self._logger.debug(f"Binding to addr: {':'.join(map(str, socketname))}")

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

    def send(self, mesg, dest):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.connect(dest)
            res = sock.send(mesg.encode())
            sock.close()

        return res

    def listen(self, timeout=None):
        try:
            self._socket.listen()
            conn, addr = self._socket.accept()
            while True:
                res = conn.recv(BUFFER_SIZE)
                if res:
                    data = res
                    continue
                else:
                    break
            return data, addr
        except socket.timeout:
            return None, None

    def __del__(self):
        self.close()

    def close(self):
        if self._open:
            self._open = False
            self._socket.close()

    def run(self):
        self._logger.debug("Listening to tcp messages")
        while not self.stopped:
            data, addr = self.listen()
            if data:
                self._logger.debug(f"Received msg {data.decode()}")
                dispatcher.send(
                    signal=ON_TCP_MESSAGE,
                    sender=self,
                    data=data.decode(),
                    addr=addr,
                )

        self._logger.debug("Shutting down.")
        self.close()


class UDPListener(SocketThread):
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
        self.listen_socket.settimeout(TIMEOUT)


        socketname = self.listen_socket.getsockname()

        self._msg_buffer = deque([], maxlen=MAX_MSG_BUFF_SIZE)

        self._logger = logging.getLogger(f"UDPListener")
        self._logger.setLevel(logging.DEBUG)
        self._logger.debug(f"Binding to addr: {':'.join(map(str, socketname))}")

    def run(self):
        self._logger.debug("Listening to broadcast messages")
        while not self.stopped:
            try:
                data, addr = self.listen_socket.recvfrom(BUFFER_SIZE)
            except socket.timeout:
                continue
            if data:
                loaded_data = json.loads(data.decode())
                if loaded_data.get("msg_uuid") in self._msg_buffer:
                    continue
                else:
                    self._msg_buffer.append(loaded_data["msg_uuid"])
                self._logger.debug(f"Received msg {data}")
                dispatcher.send(
                    signal=ON_BROADCAST_MESSAGE,
                    sender=self,
                    data=loaded_data,
                    addr=addr,
                )

        self._logger.debug("Shutting down.")

        try:
            self.listen_socket.close()
        except:
            pass

class ROMulticast(Thread):
    def __init__(self, id):
        super().__init__()
        self._name = id
        self._snumber = 1
        self._rnumbers = {}
        self._received = {}
        self._holdback = []
        self._socket = socket.socket(
            socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP
        )
        self._socket.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
        self._socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        self._socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._socket.bind((MULTICAST_IP, MULTICAST_PORT))
        mreq = struct.pack("4sl", socket.inet_aton(MULTICAST_IP), socket.INADDR_ANY)
        self._socket.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)

        self._logger = logging.getLogger(f"ROMulticast")
        self._logger.setLevel(logging.DEBUG)

    def send(self, mesg: dict):
        if "uuid" not in mesg:
            mesg["uuid"] = str(uuid.uuid4())
        if "sender" not in mesg:
            mesg["sender"] = self._name
        mesg["S"] = self._snumber
        self._snumber += 1
        self._socket.sendto(json.dumps(mesg).encode(), (MULTICAST_IP, MULTICAST_PORT))

    def r_deliver(self, data):
        self._logger.debug(f"Received msg {data}")
        self._received[data["uuid"]] = data
        if self._name != data["sender"]:
            self.send(data)
        dispatcher.send(
            signal=ON_MULTICAST_MESSAGE,
            sender=self,
            data=data,
        )

    def request_missing(self, s, r):
        self._logger.debug("Implement request missing")
        pass

    def run(self):
        self._logger.debug("Listening to rom messages")
        while True:
            data = json.loads(self._socket.recv(BUFFER_SIZE).decode())
            if data["uuid"] in self._received:
                continue
            if data["sender"] in self._rnumbers:
                s = data["S"]
                if s == self._rnumbers[data["sender"]] + 1:
                    self._rnumbers[data["sender"]] += 1
                    self.r_deliver(data)
                elif s < self._rnumbers[data["sender"]] + 1:
                    continue
                else:
                    self.request_missing(s, self._rnumbers[data["sender"]])
            else:  # TODO remove this part, we dont need it because we add data["sender"] when it joins the group
                self._rnumbers[data["sender"]] = data["S"]
                self.r_deliver(data)
