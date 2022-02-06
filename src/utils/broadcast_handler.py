import json
import logging
import socket
import sys
import uuid
from collections import deque

from src.utils.common import SocketThread
from src.utils.constants import (BROADCAST_PORT, BUFFER_SIZE, LOGGING_LEVEL,
                                 MAX_MSG_BUFF_SIZE, TIMEOUT)
from src.utils.signals import ON_BROADCAST_MESSAGE


class BroadcastHandler(SocketThread):
    """
    For handling broadcasts for a participant.
    Expects and returns json data due to our implementation choices.
    """
    def __init__(self, server_queue):
        """Set up a socket for this listener."""
        super().__init__(server_queue)
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
        self._logger.setLevel(LOGGING_LEVEL)
        self._logger.debug(f"Binding to addr: {':'.join(map(str, socketname))}")

    def send(self, msg):
        """Broadcasts json data to all participants."""
        port = BROADCAST_PORT
        msg["msg_uuid"] = str(uuid.uuid4())

        # Create a UDP socket
        broadcast_socket = socket.socket(
            socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP
        )
        # TODO On linux we need to do reuseport on windows reuseaddr
        if sys.platform == "win32":
            broadcast_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        else:
            broadcast_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        broadcast_socket.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        broadcast_socket.sendto(
            str.encode(json.dumps(msg)), ("<broadcast>", port)
        )
        broadcast_socket.close()

    def run(self):
        #self._logger.debug("Listening to broadcast messages")
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
                self.emit(
                    signal=ON_BROADCAST_MESSAGE,
                    data=loaded_data,
                    addr=addr,
                )

        self._logger.debug("Shutting down.")

        try:
            self.listen_socket.close()
        except:
            pass
