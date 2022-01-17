import json
import logging
from ntpath import join
import socket
import os
import sys
import uuid

from louie import dispatcher

from src.utils.listeners import TCPListener, UDPListener
from src.utils.signals import ON_BROADCAST_MESSAGE, ON_ENTRY_REQUEST, ON_TCP_MESSAGE

from ..utils.constants import ACCEPT_CLIENT, ACCEPT_ENTRY, BROADCAST_PORT, DENY_ENTRY, IDENT_CLIENT, MAX_ENTRIES, MAX_TRIES, REQUEST_ENTRY, SHUTDOWN_SERVER, UPDATE_ENTRIES
from ..utils.constants import BUFFER_SIZE
from ..utils.constants import CLIENT_BASE_PORT
from ..utils.util import broadcast


class Client:
    def __init__(self, number):
        self._tcp_listener = TCPListener()
        self._udp_listener = UDPListener()
        self._uuid = str(uuid.uuid4())
        # for calling and verifying purposes
        self.number = number
        self.entries = None
        self.server = None
        self._logger = logging.getLogger(f"Client No. {self.number}") # with UUID {self._uuid}")
        self._logger.setLevel(logging.DEBUG)

        self._setup_connections()

    def _setup_connections(self):
        dispatcher.connect(
            self._on_tcp_msg, signal=ON_TCP_MESSAGE, sender=self._tcp_listener
        )
        dispatcher.connect(
            self._on_udp_msg, signal=ON_BROADCAST_MESSAGE, sender=self._udp_listener
        )
        dispatcher.connect(
            self._on_entry_request, signal=ON_ENTRY_REQUEST, sender=self.number
        )

    def find_server(self):
        mes = {
            "intention": IDENT_CLIENT,
            "uuid": f"{self._uuid}",
            "address": self._tcp_listener.address,
            "port": self._tcp_listener.port,
        }
        broadcast(BROADCAST_PORT, mes)

        for _ in range(MAX_TRIES):
            res, add = self._tcp_listener.listen(1)
            if res is not None:
                data = json.loads(res)
                if data.get("intention") == ACCEPT_CLIENT:
                    self._logger.debug(f"Recieved client accept message {data} from {add}")
                    self.server = (data.get("address"),data.get("port"))
                    break

    def _on_entry_request(self):
        if self.server == None:
            self._logger.debug(f"Client No. {self.number} asked to request entry, but didn't have a server.")
        else:
            mes = json.dumps({
                "intention": REQUEST_ENTRY,
                "uuid": f"{self._uuid}",
                "address": self._tcp_listener.address,
                "port": self._tcp_listener.port,
                "number": self.number
            })
            len = mes.encode().__len__()
            for _ in range(MAX_TRIES):
                try:
                    res = self._tcp_listener.send(mes, self.server)
                except ConnectionRefusedError:
                    self._logger.warn(f"Client No. {self.number} was refused when trying to connect to its server, will look for a new one.")
                    self.server = None
                    self.find_server()
                    return
                if res != len:
                    self._logger.warn(f"Client No. {self.number} was unable to send a complete message! Retrying.")
                else:
                    self._logger.debug("Success! Waiting for response")
                    return
            self._logger.warn(f"Client No. {self.number} discarding current server, connection seems to be malfunctioning.")
            self.server = None
            self.find_server()

    def _on_udp_msg(self, data=None, addr=None):
        #TODO Actually send this
        if data["intention"] == UPDATE_ENTRIES:
            self.entries = data["entries"]
            self._logger.info(f"Current Entries: {self.entries} of {MAX_ENTRIES}")

    def _on_tcp_msg(self, data=None, addr=None):
        res = json.loads(data)
        #TODO actually send this
        if res["intention"] == SHUTDOWN_SERVER:
            self.server == None
            self.find_server()
        elif res["intention"] == ACCEPT_CLIENT:
            self._logger.info(f"Received random client accept message: {res}")
        elif res["intention"] == ACCEPT_ENTRY:
            self._logger.info("Entry granted, please enjoy yourself!")
            self.entries = res["entries"]
            self._logger.info(f"Current Entries: {self.entries} of {MAX_ENTRIES}")
        elif res["intention"] == DENY_ENTRY:
            self._logger.info("Entry denied. Seems like we are full, sorry.")
            #TODO shut this client down here?
    
    def _shut_down(self):
        self._tcp_listener.join()
        self._udp_listener.join()

    def run(self):
        while self.server == None:
            self._logger.debug(f"Client {self.number} trying to find a server.")
            self.find_server()

        self._logger.debug(f"Connected to server {self.server}")
        self._tcp_listener.start()
        self._udp_listener.start()

        try:
            while True:
                input("Please enter anything to send a request")
                #TODO outsource this?
                dispatcher.send(
                    signal=ON_ENTRY_REQUEST,
                    sender=self.number
                )
        except KeyboardInterrupt:
            self._logger.debug("Interrupted.")
            self._shut_down()
            try:
                sys.exit(0)
            except SystemExit:
                os._exit(0)
