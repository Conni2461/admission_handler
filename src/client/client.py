import logging
import os
import sys
import uuid

from louie import dispatcher
from src.utils.broadcast_handler import BroadcastHandler
from src.utils.signals import (ON_BROADCAST_MESSAGE, ON_ENTRY_REQUEST,
                               ON_TCP_MESSAGE)
from src.utils.tcp_handler import TCPHandler

from ..utils.constants import (ACCEPT_CLIENT, ACCEPT_ENTRY, DENY_ENTRY,
                               IDENT_CLIENT, MAX_ENTRIES, MAX_TRIES,
                               REQUEST_ENTRY, SHUTDOWN_SERVER, SHUTDOWN_SYSTEM, UPDATE_ENTRIES)


class Client:
    def __init__(self, number):
        """Set up handlers, uuid etc."""
        self._tcp_listener = TCPHandler()
        self._broadcast_handler = BroadcastHandler()
        self._uuid = str(uuid.uuid4())
        # a human readable number for calling and verifying purposes
        self.number = number
        self.entries = None
        self.server = None
        self._logger = logging.getLogger(f"Client No. {self.number}") # with UUID {self._uuid}")
        self._logger.setLevel(logging.DEBUG)

        dispatcher.connect(
            self._on_tcp_msg, signal=ON_TCP_MESSAGE, sender=self._tcp_listener
        )
        dispatcher.connect(
            self._on_broadcast, signal=ON_BROADCAST_MESSAGE, sender=self._broadcast_handler
        )
        dispatcher.connect(
            self._on_entry_request, signal=ON_ENTRY_REQUEST, sender=self.number
        )

    def find_server(self):
        """Broadcast this clients existence to the system and register the first server that answers."""
        mes = {
            "intention": IDENT_CLIENT,
            "uuid": f"{self._uuid}",
            "address": self._tcp_listener.address,
            "port": self._tcp_listener.port,
        }
        self._broadcast_handler.send(mes)

        #TODO potentially include this in normal tcp listening routine
        for _ in range(MAX_TRIES):
            data, add = self._tcp_listener.listen()
            if data is not None:
                self._logger.debug(data)
                if data.get("intention") == ACCEPT_CLIENT:
                    self._logger.debug(f"Recieved client accept message {data} from {add}")
                    self.server = (data.get("address"),data.get("port"))
                    break

    def _on_entry_request(self):
        if self.server == None:
            self._logger.debug(f"Client No. {self.number} asked to request entry, but didn't have a server. Please try again.")
        else:
            mes = {
                "intention": REQUEST_ENTRY,
                "uuid": f"{self._uuid}",
                "address": self._tcp_listener.address,
                "port": self._tcp_listener.port,
                "number": self.number
            }
            success = self._tcp_listener.send(mes, self.server)
            if success:
                self._logger.debug("Success! Waiting for response")
            else:
                self._logger.warn(f"Client No. {self.number} discarding current server, connection seems to be malfunctioning.")
                self.server = None
                self.find_server()

    #TODO potentially discard address in the handler
    def _on_broadcast(self, data=None, addr=None):
        if data["intention"] == SHUTDOWN_SYSTEM:
            self._shut_down()

    def _on_tcp_msg(self, data=None, addr=None):
        if data["intention"] == SHUTDOWN_SERVER:
            self.server == None
            self.find_server()
        elif data["intention"] == ACCEPT_CLIENT:
            self._logger.info(f"Received random client accept message: {data}")
        elif data["intention"] == ACCEPT_ENTRY:
            self._logger.info("Entry granted, please enjoy yourself!")
            self.entries = data["entries"]
            self._logger.info(f"Current Entries: {self.entries} of {MAX_ENTRIES}")  
        elif data["intention"] == UPDATE_ENTRIES:
            #TODO actually send this
            self.entries = data["entries"]
            self._logger.info(f"Current Entries: {self.entries} of {MAX_ENTRIES}")
        elif data["intention"] == DENY_ENTRY:
            self._logger.info("Entry denied. Seems like we are full, sorry.")
            #TODO shut this client down here?
    
    def _shut_down(self):
        self._tcp_listener.join()
        self._broadcast_handler.join()

    def run(self):
        #TODO potentially make less spammy and include in normal routine
        while self.server == None:
            self._logger.debug(f"Client {self.number} trying to find a server.")
            self.find_server()

        self._logger.debug(f"Connected to server {self.server}")
        self._tcp_listener.start()
        self._broadcast_handler.start()

        try:
            while True:
                input("Please enter anything to send a request\n")
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
