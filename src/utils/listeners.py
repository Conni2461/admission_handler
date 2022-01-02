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
    Purpose,
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
        self._snumber = 0
        self._rnumbers = {}
        self._received = {}

        self._out = {}
        self._out_a = {}
        self._holdback = {}

        self._aq = 0  # Largest agreed seqeunce number
        self._pq = 0  # Largest proposed sequence number

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

    # TODO call this
    def register_new_member(self, id):
        self._rnumbers[id] = 0

    def send(self, mesg: dict):
        # Inject purpose
        if "purpose" not in mesg:
            mesg["purpose"] = str(Purpose.REAL_MSG)

        # inject message identifier
        if "i" not in mesg:
            mesg["i"] = str(uuid.uuid4())

        # Sender is not part of message if it wasnt send yet,
        # so this means this is the original sender of the message
        # So we also place this message in `self._out`
        if "sender" not in mesg:
            mesg["sender"] = self._name
            self._out[mesg["i"]] = mesg
            self._out_a[mesg["i"]] = []

        mesg["S"] = self._snumber
        self._snumber += 1
        self._socket.sendto(json.dumps(mesg).encode(), (MULTICAST_IP, MULTICAST_PORT))

    def _answer(self, i, r, pq):
        mesg = {"purpose": str(Purpose.PROP_SEQ), "r": r, "i": i, "pq": pq}
        self._socket.sendto(json.dumps(mesg).encode(), (MULTICAST_IP, MULTICAST_PORT))

    def _collect(self, data):
        if data["r"] != self._name:
            return
        i = data["i"]
        pq = data["pq"]
        self._out_a[i].append(pq)
        if len(self._out_a[i]) != len(self._rnumbers):
            return
        a = max(self._out_a[i])
        mesg = {"purpose": str(Purpose.FIN_SEQ), "i": i, "a": a}
        self._socket.sendto(json.dumps(mesg).encode(), (MULTICAST_IP, MULTICAST_PORT))

    def _process(self, data):
        # self._logger.debug(f"Received msg {data}")
        self._received[data["i"]] = data
        if self._name != data["sender"]:
            self.send(data)

        self._pq = max(self._aq, self._pq) + 1
        data["pq"] = self._pq
        self._holdback[data["i"]] = data
        # TODO Maybe this answer should be tcp rather than a multicast
        self._answer(data["i"], data["sender"], data["pq"])

    def _deliver(self, data):
        i = data["i"]
        a = data["a"]
        self._aq = max(self._aq, a)
        mesg = None
        if i in self._out:
            mesg = self._out[i]
        else:
            mesg = self._holdback.pop(i)
            del mesg["pq"]
        mesg["a"] = a
        dispatcher.send(
            signal=ON_MULTICAST_MESSAGE,
            sender=self,
            data=mesg,
        )

    # TODO implement _request_missing
    def _request_missing(self, s, r):
        self._logger.debug(f"Implement request missing: {s}, {r}")
        pass

    def run(self):
        self._logger.debug("Listening to rom messages")
        while True:
            data = json.loads(self._socket.recv(BUFFER_SIZE).decode())
            if data["purpose"] == str(Purpose.PROP_SEQ):
                self._collect(data)
                continue

            if data["purpose"] == str(Purpose.FIN_SEQ):
                self._deliver(data)
                continue

            # Only purpose REAL_MSG should be left, so if its something else log it
            if data["purpose"] != str(Purpose.REAL_MSG):
                self._logger.error(f"Bad message {data}")
                continue

            if data["sender"] == self._name:
                continue
            if data["i"] in self._received:
                continue
            if data["sender"] in self._rnumbers:
                s = data["S"]
                if s == self._rnumbers[data["sender"]] + 1:
                    self._rnumbers[data["sender"]] += 1
                    self._process(data)
                elif s < self._rnumbers[data["sender"]] + 1:
                    continue
                else:
                    self._request_missing(s, self._rnumbers[data["sender"]])
            # TODO remove this part, we dont need it because we add data["sender"] when it joins the group
            else:
                self._rnumbers[data["sender"]] = data["S"]
                self._process(data)
