import uuid
import json
import logging
import socket
import struct
import select
import sys
import copy
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


class ROMulticast(SocketThread):
    def __init__(self, id):
        super().__init__()
        self._name = id
        self._snumber = 0
        self._rnumbers = {self._name: self._snumber}
        self._received = {}
        self._holdback = {}

        self._out = {}
        self._out_a = {}
        self._deliver_queue = {}

        self._aq = 0  # Largest agreed seqeunce number
        self._pq = 0  # Largest proposed sequence number

        self._listener_socket = socket.socket(
            socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP
        )
        self._listener_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        self._listener_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._listener_socket.bind(("", MULTICAST_PORT))
        mreq = struct.pack("4sl", socket.inet_aton(MULTICAST_IP), socket.INADDR_ANY)
        self._listener_socket.setsockopt(
            socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq
        )

        self._sender_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sender_socket.settimeout(0.2)
        ttl = struct.pack("b", 1)
        self._sender_socket.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, ttl)

        self._logger = logging.getLogger("ROMulticast")
        self._logger.setLevel(logging.DEBUG)

    def register_new_member(self, id):
        self._rnumbers[id] = 0

    def set_r_list(self, rnumbers):
        self._rnumbers.update(rnumbers)

    def _send(self, mesg: dict):
        mesg["sender"] = self._name
        self._snumber += 1
        mesg["S"] = self._snumber

        self._out[mesg["id"]] = mesg
        self._sender_socket.sendto(
            json.dumps(mesg).encode(), (MULTICAST_IP, MULTICAST_PORT)
        )

    def send(self, mesg: dict):
        # Inject purpose
        if "purpose" not in mesg:
            mesg["purpose"] = str(Purpose.REAL_MSG)

        # inject message identifier
        if "id" not in mesg:
            mesg["id"] = str(uuid.uuid4())

        # Sender is not part of message if it wasnt send yet,
        # so this means this is the original sender of the message
        # So we also place this message in `self._out`
        if "sender" not in mesg:
            mesg["original"] = self._name
            self._out_a[mesg["id"]] = []

        self._send(mesg)

    def _propose_order(self, data: dict, addr):
        self._deliver_queue[data["id"]] = data
        self._pq = max(self._aq, self._pq) + 1
        mesg = {
            "purpose": str(Purpose.PROP_SEQ),
            "mesg_id": data["id"],
            "pq": self._pq,
            "id": str(uuid.uuid4()),
        }
        self._sender_socket.sendto(json.dumps(mesg).encode(), addr)

    def _collect_order_proposals(self, data: dict):
        id = data["mesg_id"]
        pq = data["pq"]
        self._out_a[id].append(pq)
        if len(self._out_a[id]) != len(self._rnumbers):
            return
        a = max(self._out_a[id])
        mesg = {
            "purpose": str(Purpose.FIN_SEQ),
            "mesg_id": id,
            "a": a,
            "id": str(uuid.uuid4()),
        }
        self._send(mesg)

    def _deliver_message(self, data: dict):
        id = data["mesg_id"]
        a = data["a"]
        self._aq = max(self._aq, a)
        if id not in self._deliver_queue:
            if id not in self._received:
                self._logger.error(
                    "Something went wrong with putting the message into the _deliver_queue"
                )
            return
        mesg = self._deliver_queue.pop(id)
        mesg["a"] = a
        dispatcher.send(
            signal=ON_MULTICAST_MESSAGE,
            sender=self,
            data=mesg,
        )

    def _process_message(self, data: dict, addr):
        self._rnumbers[data["sender"]] += 1

        if data["purpose"] == str(Purpose.REAL_MSG):
            self._propose_order(data, addr)
        elif data["purpose"] == str(Purpose.FIN_SEQ):
            self._deliver_message(data)
        else:
            self._logger.error(f"Bad message {data}")

    def _check_for_next_msg(self, s, sender):
        found = None
        for id, msg in self._holdback.items():
            if msg["data"]["S"] == s and msg["data"]["sender"] == sender:
                found = id
                break
        if found is not None:
            print("found a message")
            return self._holdback.pop(found)
        return None

    def _request_missing(self, data: dict, addr, s, r):
        self._holdback[data["id"]] = {"data": data, "addr": addr}
        sender = data["sender"]
        r_i = r + 1
        stop = False
        nacks = []
        while r_i < s:
            # Check if we have the message already in the holdback queue. If we
            # have, take it out and deliver it
            msg = self._check_for_next_msg(r_i, sender)
            if msg is not None:
                if not stop:
                    self._process_message(msg["data"], msg["addr"])
            else:
                stop = True
                nacks.append(r_i)
            r_i += 1

        self._logger.debug(f"TODO nack: {nacks}")
        mesg = {
            "purpose": str(Purpose.NACK),
            "id": str(uuid.uuid4),
            "nacks": nacks,
        }
        self._sender_socket.sendto(json.dumps(mesg).encode(), addr)

    def _handle(self, data: dict, addr):
        if data["purpose"] == str(Purpose.PROP_SEQ):
            self._collect_order_proposals(data)
            return
        elif data["purpose"] == str(Purpose.NACK):
            for nack in data["nacks"]:
                # Iterating over all thoes messages sucks. We need a better way
                # to store the out messages.
                # Check `S = data` would work
                for out_messages in self._out.values():
                    if out_messages["data"]["S"] == nack:
                        self._sender_socket.send(out_messages, addr)
                        break
            return

        sender = data["sender"]
        id = data["id"]
        if sender not in self._rnumbers:
            self._logger.error(f"Don't know rnumer {data['sender']}")
            return

        # Reliable Multicast
        if id not in self._received:
            self._received[id] = data
            if self._name != sender:
                # We changed the data because we changed the sender
                # which fucked up everything below. So deepcopy ftw
                # Its not like it cost me 4 hours
                self.send(copy.deepcopy(data))

            # Basic Delivery
            s = data["S"]
            if s == self._rnumbers[sender] + 1:
                self._process_message(data, addr)
                s += 1
                next_msg = self._check_for_next_msg(s, sender)
                while next_msg is not None:
                    self._process_message(next_msg, addr)
                    s += 1
                    next_msg = self._check_for_next_msg(s, sender)
            elif s <= self._rnumbers[sender]:
                self._logger.debug(
                    f"skipping message {id} from {sender} with {s} and {self._rnumbers}"
                )
            else:
                print(s, self._rnumbers)
                self._request_missing(data, addr, s, self._rnumbers[sender])
        else:
            if data["S"] == self._rnumbers[sender] + 1:
                self._rnumbers[data["sender"]] += 1

    def run(self):
        self._logger.debug(f"Listening to rom messages {self._name}")
        while not self.stopped:
            try:
                ready_socks, _, _ = select.select(
                    [self._listener_socket, self._sender_socket], [], []
                )
                for sock in ready_socks:
                    data, addr = sock.recvfrom(1024)
                    self._handle(json.loads(data.decode()), addr)
            except socket.timeout:
                continue

        self._logger.debug("Shutting down.")

        try:
            self._listener_socket.close()
            self._sender_socket.close()
        except Exception as e:
            self._logger.error(f"Could not close socket: {e}.")
