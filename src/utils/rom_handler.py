import copy
import json
import logging
import queue
import select
import socket
import struct
import sys
import uuid

from src.utils.common import SocketThread
from src.utils.constants import (LOGGING_LEVEL, MULTICAST_IP, MULTICAST_PORT,
                                 TIMEOUT, Intention, Purpose)
from src.utils.signals import ON_MULTICAST_MESSAGE


class ROMulticastHandler(SocketThread):
    def __init__(self, id, view, server_queue, timeout=TIMEOUT):
        super().__init__(server_queue)
        self._name = id
        self._snumber = 0
        self._rnumbers = {self._name: self._snumber}
        self._current_group_view = view
        self._received = {}
        self._holdback = {}  # { id = { data: data, addr: addr } } dict

        self._out = {}  # { snumber: msg, ... } dict
        self._out_a = {}
        self._group_view_backlog = {}
        self._deliver_queue = {}

        self._aq = 0  # Largest agreed seqeunce number
        self._pq = 0  # Largest proposed sequence number

        self._paused_queue = queue.Queue()
        self._paused = False

        self._listener_socket = socket.socket(
            socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP
        )
        if sys.platform == "win32":
            self._listener_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        else:
            self._listener_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        self._listener_socket.bind(("", MULTICAST_PORT))
        mreq = struct.pack("4sl", socket.inet_aton(MULTICAST_IP), socket.INADDR_ANY)
        self._listener_socket.setsockopt(
            socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq
        )
        self._listener_socket.settimeout(timeout)

        self._sender_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sender_socket.settimeout(0.2)
        ttl = struct.pack("b", 1)
        self._sender_socket.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, ttl)

        self._logger = logging.getLogger("ROMulticast")
        self._logger.setLevel(LOGGING_LEVEL)

    def set_group_view(self, view):
        self._current_group_view = view
        # we need to make a copy because while we iterate thought it there is a
        # good chance that thread/louie suspends the iterating to process a new
        # message but because we are still iterating a removal of a value from
        # `_out_a` could lead to an exception.
        ids = list(self._out_a.keys())
        for id in ids:
            if id not in self._out_a:
                continue
            done = self._complete_proposal(id, self._out_a[id])
            if done:
                del self._out_a[id]

    def register_new_member(self, id):
        self._rnumbers[id] = 0

    def sync_state(self, rnumbers, deliver_queue):
        self._rnumbers.update(rnumbers)
        self._deliver_queue.update(deliver_queue)

    def pause(self, sendout=True):
        if not self._paused:
            self._logger.info("pausing rom")
        self._paused = True
        if sendout:
            self.send({"purpose": str(Purpose.STOP)})

    def resume(self, value=0, sendout=True):
        if self._paused:
            self._logger.info("resuming rom")
        self._paused = False
        if sendout:
            self.send({"purpose": str(Purpose.RESUME), "value": value})

        while not self._paused_queue.empty():
            self._send(self._paused_queue.get())

    def _send(self, mesg: dict):
        mesg["sender"] = self._name
        self._snumber += 1
        mesg["S"] = self._snumber

        self._out[self._snumber] = mesg
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

        if "sender" not in mesg:
            mesg["original"] = self._name
            self._out_a[mesg["id"]] = {}
            self._group_view_backlog[mesg["id"]] = copy.deepcopy(
                self._current_group_view
            )

        if self._paused and (
            mesg["purpose"] != str(Purpose.STOP)
            and mesg["purpose"] != str(Purpose.RESUME)
        ):
            self._paused_queue.put(mesg)
            return

        self._send(mesg)

    def _propose_order(self, data: dict, addr):
        self._deliver_queue[data["id"]] = data
        self._pq = max(self._aq, self._pq) + 1
        mesg = {
            "purpose": str(Purpose.PROP_SEQ),
            "mesg_id": data["id"],
            "pq": self._pq,
            "id": str(uuid.uuid4()),
            "sender": self._name,
        }
        self._sender_socket.sendto(json.dumps(mesg).encode(), addr)

    def _collect_order_proposals(self, data: dict):
        id = data["mesg_id"]
        pq = data["pq"]

        if id not in self._out_a:
            return
        self._out_a[id][data["sender"]] = pq
        done = self._complete_proposal(id, self._out_a[id])
        if done:
            del self._out_a[id]

    def _complete_proposal(self, id, value):
        prev_participants = set(self._group_view_backlog[id].keys())
        curr_participants = set(self._current_group_view.keys())
        diff = prev_participants.intersection(curr_participants) - set(value.keys())

        if len(diff) > 0:
            return False
        a = max(value.values())
        mesg = {
            "purpose": str(Purpose.FIN_SEQ),
            "mesg_id": id,
            "a": a,
            "id": str(uuid.uuid4()),
        }
        self._send(mesg)
        return True

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

        if mesg["purpose"] == str(Purpose.STOP):
            self.pause(False)
            return
        elif mesg["purpose"] == str(Purpose.RESUME):
            self.resume(sendout=False)
            self.emit(
                signal=ON_MULTICAST_MESSAGE,
                data={"intention": str(Intention.OM_RESULT), "result": mesg["value"]},
            )
            return

        self.emit(
            signal=ON_MULTICAST_MESSAGE,
            sender=self,
            data=mesg,
        )

    def _process_message(self, data: dict, addr):
        self._rnumbers[data["sender"]] += 1

        if (
            data["purpose"] == str(Purpose.REAL_MSG)
            or data["purpose"] == str(Purpose.STOP)
            or data["purpose"] == str(Purpose.RESUME)
        ):
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
                if nack in self._out:
                    self._sender_socket.sendto(
                        json.dumps(self._out[nack]).encode(), addr
                    )
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
                    self._process_message(next_msg["data"], addr)
                    s += 1
                    next_msg = self._check_for_next_msg(s, sender)
            elif s <= self._rnumbers[sender]:
                self._logger.debug(
                    f"skipping message {id} from {sender} with {s} and {self._rnumbers}"
                )
            else:
                self._request_missing(data, addr, s, self._rnumbers[sender])
        else:
            if data["S"] == self._rnumbers[sender] + 1:
                self._rnumbers[data["sender"]] += 1

    def run(self):
        self._logger.debug(f"Listening to rom messages {self._name}")
        while not self.stopped:
            try:
                ready_socks, _, _ = select.select(
                    [self._listener_socket, self._sender_socket], [], [], TIMEOUT
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
