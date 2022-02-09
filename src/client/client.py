import logging
import os
import queue
import sys
import uuid

from src.utils.broadcast_handler import BroadcastHandler
from src.utils.signals import (ON_BROADCAST_MESSAGE, ON_ENTRY_REQUEST,
                               ON_TCP_MESSAGE)
from src.utils.tcp_handler import TCPHandler

from ..utils.common import Invokeable, SocketThread
from ..utils.constants import LOGGING_LEVEL, MAX_ENTRIES, MAX_TRIES, Intention
from .signals import (ON_ACCESS_RESPONSE, ON_CLIENT_SHUTDOWN, ON_COUNT_CHANGED,
                      ON_REQUEST_ACCESS, ON_SERVER_CHANGED)


class KeyboardListener(SocketThread):
    def __init__(self, queue):
        super().__init__(queue)

    def run(self):
        while not self.stopped:
            inpt = input("Please enter dec to decrease or anything else to send an entry request\n")
            if inpt == "dec":
                self.emit(
                    signal=ON_ENTRY_REQUEST,
                    inc=False
                )
            elif inpt == "exit":
                self.emit(
                    signal="quit",
                )
                break
            else:
                self.emit(
                    signal=ON_ENTRY_REQUEST,
                )


class Client:

    QUEUE = queue.SimpleQueue()
    UI_QUEUE = queue.SimpleQueue()

    def __init__(self, number):
        """Set up handlers, uuid etc."""
        self._tcp_listener = TCPHandler(self.QUEUE)
        self._broadcast_handler = BroadcastHandler(self.QUEUE)
        self._uuid = str(uuid.uuid4())
        # a human readable number for calling and verifying purposes
        self.number = number
        self.entries = None
        self.server = None
        self._logger = logging.getLogger(f"Client No. {self.number}") # with UUID {self._uuid}")
        self._logger.setLevel(LOGGING_LEVEL)

        self._keyboard_listener = KeyboardListener(self.QUEUE)

    def find_server(self):
        """Broadcast this clients existence to the system and register the first server that answers."""
        mes = {
            "intention": str(Intention.IDENT_CLIENT),
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
                if data.get("intention") == str(Intention.ACCEPT_CLIENT):
                    self._logger.debug(f"Recieved client accept message {data} from {add}")
                    self.server = (data.get("address"),data.get("port"))
                    mes = {
                        "intention": str(Intention.CHOOSE_SERVER),
                        "uuid": self._uuid,
                        "address": self._tcp_listener.address,
                        "port": self._tcp_listener.port
                    }
                    if self._tcp_listener.send(mes, self.server):
                        self.entries = data["entries"]
                        self.UI_QUEUE.put(Invokeable(ON_SERVER_CHANGED, server=data["uuid"], count=self.entries or 0))
                        break
                    else:
                        self.server = None
                        self._logger.warn("Failed to notify chosen server, discarding choice!")

    def _on_action_request(self, inc=True):

        if inc:
            self.UI_QUEUE.put(Invokeable(ON_REQUEST_ACCESS))

        if self.server == None:
            self._logger.debug(f"Client No. {self.number} asked to request an action, but didn't have a server. Please try again.")
            msg = "Could not find a server. Please try again."
            self.find_server()
        else:
            mes = {
                "intention": str(Intention.REQUEST_ACTION),
                "uuid": f"{self._uuid}",
                "address": self._tcp_listener.address,
                "port": self._tcp_listener.port,
                "number": self.number,
                "increase": inc
            }
            if self._tcp_listener.send(mes, self.server):
                self._logger.debug("Success! Waiting for response")
            else:
                self._logger.warn(f"Client No. {self.number} discarding current server, connection seems to be malfunctioning.")
                self.server = None

                msg = "Could not connect to server. Please try again."
                self.UI_QUEUE.put(Invokeable(ON_ACCESS_RESPONSE, response={"message": msg, "status": False}))
                self.find_server()

    #TODO potentially discard address in the handler
    def _on_broadcast(self, data=None, addr=None):
        if data["intention"] == str(Intention.SHUTDOWN_SYSTEM):
            self._shut_down()

    def _on_tcp_msg(self, data=None, addr=None):
        if data["intention"] == str(Intention.SHUTDOWN_SERVER):
            self.server == None
            self.find_server()
        elif data["intention"] == str(Intention.ACCEPT_CLIENT):
            self._logger.info(f"Received random client accept message: {data}")
        elif data["intention"] == str(Intention.ACCEPT_ENTRY):
            msg = "Entry granted, please enjoy yourself!"
            self._logger.info(msg)

            self.UI_QUEUE.put(Invokeable(ON_ACCESS_RESPONSE, response={"status": True, "message": msg}))

        elif data["intention"] == str(Intention.UPDATE_ENTRIES):
            self.entries = data["entries"]
            self._logger.info(f"Current Entries: {self.entries} of {MAX_ENTRIES}")

            self.UI_QUEUE.put(Invokeable(ON_ACCESS_RESPONSE, response={"status": None}))
            self.UI_QUEUE.put(Invokeable(ON_COUNT_CHANGED, count=data["entries"]))

        elif data["intention"] == str(Intention.DENY_ENTRY):
            msg = "Entry denied. Seems like we are full, sorry."
            self._logger.info(msg)
            #TODO shut this client down here?

            self.UI_QUEUE.put(Invokeable(ON_ACCESS_RESPONSE, response={"message": msg, "status": False}))

    def _shut_down(self):
        self._keyboard_listener.join()
        self._tcp_listener.send({"intention": str(Intention.SHUTDOWN_CLIENT), "uuid": self._uuid},self.server)
        self._tcp_listener.join()
        self._broadcast_handler.join()

        self.UI_QUEUE.put(Invokeable(ON_CLIENT_SHUTDOWN))

    def stop(self):
        raise KeyboardInterrupt

    def run(self):
        #TODO potentially make less spammy and include in normal routine

        while self.server == None:
            self._logger.debug(f"Client {self.number} trying to find a server.")
            self.find_server()

        self._logger.debug(f"Connected to server {self.server}")
        self._tcp_listener.start()
        self._broadcast_handler.start()
        self._keyboard_listener.start()

        try:
            while True:
                try:
                    item = self.QUEUE.get(block=False)
                    if item.signal == ON_TCP_MESSAGE:
                        self._on_tcp_msg(**item.kwargs)
                    elif item.signal == ON_BROADCAST_MESSAGE:
                        self._on_broadcast(**item.kwargs)
                    elif item.signal == ON_ENTRY_REQUEST:
                        self._on_action_request(**item.kwargs)
                    elif item.signal == "quit":
                        break

                except queue.Empty:
                    pass
        except KeyboardInterrupt:
            self._logger.debug("Interrupted.")

        self._shut_down()
        try:
            sys.exit(0)
        except SystemExit:
            os._exit(0)
