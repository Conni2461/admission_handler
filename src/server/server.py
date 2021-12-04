import uuid
import json
import logging
from louie import dispatcher

from ..utils.constants import (
    BROADCAST_PORT,
    IDENT_CLIENT,
    IDENT_SERVER,
    MAX_TRIES,
    State,
)
from ..utils.signals import ON_BROADCAST_MESSAGE
from ..utils.util import broadcast, CustomLogger
from ..utils.listeners import TCPListener, UDPListener

logging.basicConfig(format="%(levelname)s:%(message)s", level=logging.DEBUG)


class Server:
    def __init__(self):
        self._state = State.PENDING
        self._tcp_listener = TCPListener()
        self._udp_listener = UDPListener()
        self._uuid = uuid.uuid4()
        self._group_view = dict()
        self._logger = logging.getLogger(f"Server {self._uuid}")
        self._logger.setLevel(logging.DEBUG)

    def request_join(self):
        mes = {
            "intention": IDENT_SERVER,
            "uuid": f"{self._uuid}",
            "address": self._tcp_listener.address,
            "port": self._tcp_listener.port,
        }

        broadcast(BROADCAST_PORT, json.dumps(mes))

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

        self._logger.debug(f"{self._state}, {self._group_view}")
        self._udp_listener.start()

        dispatcher.connect(
            self.on_udp_msg, signal=ON_BROADCAST_MESSAGE, sender=self._udp_listener
        )

    def on_udp_msg(self, data=None, addr=None):
        if self._state == State.LEADER:
            res = json.loads(data)
            if res["intention"] == IDENT_SERVER:
                self._group_view[res["uuid"]] = (res["address"], res["port"])
                self._tcp_listener.send("hello", self._group_view[res["uuid"]])
                self._logger.debug(f"{self._state}, {self._group_view}")
                # TODO check for smaller IP and maybe start new election
            elif res["intention"] == IDENT_CLIENT:
                self._logger.debug(f"TODO: {res}")
            else:
                # TODO: handle other broadcasts?
                self._logger.debug("How did we get here?")
        else:
            self._logger.debug("Received broadcast message:", data, addr)

    def run(self):
        while True:
            pass
