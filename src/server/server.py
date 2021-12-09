import json
import logging
import socket
import uuid

from louie import dispatcher

from ..utils.constants import (BROADCAST_PORT, IDENT_CLIENT, IDENT_SERVER,
                               MAX_TRIES, UPDATE_GROUP_VIEW, State)
from ..utils.listeners import TCPListener, UDPListener
from ..utils.signals import ON_BROADCAST_MESSAGE, ON_TCP_MESSAGE
from ..utils.util import CustomLogger, broadcast

logging.basicConfig(format="%(levelname)s:%(message)s", level=logging.DEBUG)


class Server:
    def __init__(self):
        self._state = State.PENDING
        self._tcp_listener = TCPListener()
        self._udp_listener = UDPListener()
        self._uuid = str(uuid.uuid4())
        self._group_view = dict()
        self._current_leader = None
        self._logger = logging.getLogger(f"Server {self._uuid}")
        self._logger.setLevel(logging.DEBUG)

        dispatcher.connect(self._on_tcp_msg, signal=ON_TCP_MESSAGE, sender=self._tcp_listener)
        dispatcher.connect(
            self._on_udp_msg, signal=ON_BROADCAST_MESSAGE, sender=self._udp_listener
        )

        # TODO: check why we are receiving our own join request twice?

    def _request_join(self):
        mes = {
            "intention": IDENT_SERVER,
            "uuid": f"{self._uuid}",
            "address": self._tcp_listener.address,
            "port": self._tcp_listener.port,
        }

        self._logger.debug("Requesting join.")
        broadcast(BROADCAST_PORT, mes)

        for _ in range(MAX_TRIES):
            res, add = self._tcp_listener.listen()
            if res is not None:
                self._state = State.MEMBER
                break

        if self._state == State.PENDING:
            self._state = State.LEADER
            self._group_view[self._uuid] = (
                self._tcp_listener.address,
                self._tcp_listener.port,
            )

        self._logger.debug(f"In Request Join: {self._state}, {self._group_view}")
        self._udp_listener.start()

    def _on_udp_msg(self, data=None, addr=None):
        if self._state == State.LEADER:
            if data["intention"] == IDENT_SERVER and data["uuid"] != self._uuid:
                self._group_view[data["uuid"]] = (data["address"], data["port"])
                self._tcp_listener.send(json.dumps({"intention": "wozzaaa"}), self._group_view[data["uuid"]])
                self._logger.debug("Received server join request from {}".format((data["address"], data["port"])))

                self._logger.debug("New group view is: {}".format(self._group_view))

                self._distribute_group_view()

                if self._election_required():
                    self._start_election()

            elif data["intention"] == IDENT_CLIENT:
                self._logger.debug(f"TODO: {data}")
            else:
                # TODO: handle other broadcasts?
                if (data["uuid"] != self._uuid):
                    # TODO: maybe ignore udp msg uuids that we sent ourselves
                    self._logger.debug(f"How did we get here?\n {data}")
        else:
            self._logger.debug(f"Received broadcast message: {data} from {addr}")

    def _start_election(self):
        pass

    def _election_required(self):
        my_ip = socket.inet_aton(self._group_view[self._uuid][0])
        return my_ip == self._get_ring()[0]

    def _get_ring(self):
        return sorted([member for member in self._group_view.keys()])

    def _distribute_group_view(self):
        for uuid, address in self._group_view.items():
            if uuid != self._uuid:
                data = {
                    "intention": UPDATE_GROUP_VIEW,
                    "group_view": self._group_view
                }
                self._tcp_listener.send(json.dumps(data), address)

    def _on_tcp_msg(self, data=None, addr=None):
        res = json.loads(data)
        if res["intention"] == UPDATE_GROUP_VIEW:
            self._group_view = res["group_view"]
            self._logger.debug(f"Received updated group view with {len(list(self._group_view.keys()))} items.")

    def run(self):

        self._request_join()
        self._tcp_listener.start()

        while True:
            pass
