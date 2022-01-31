import json
import logging
import socket
import sys

from louie import dispatcher
from src.utils.common import SocketThread
from src.utils.constants import (BUFFER_SIZE, LOGGING_LEVEL, MAX_TRIES,
                                 TIMEOUT, WINDOWS_IP)
from src.utils.signals import ON_TCP_MESSAGE


class TCPHandler(SocketThread):
    """
    For handling the TCP connections of a participant.
    Expects and returns json data due to our implementation choices.
    """
    def __init__(self, timeout=TIMEOUT):
        """Set up a socket for this listener."""
        super().__init__()
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        if sys.platform == 'win32':
            # when testing on windows 10, we were unable to bind to ""
            self._socket.bind((WINDOWS_IP, 0))
        else:
            self._socket.bind(("", 0))
        socketname = self._socket.getsockname()
        self._address = socketname[0]
        self._port = socketname[1]
        self._socket.settimeout(timeout)
        self._open = True

        self._logger = logging.getLogger(f"TCPListener")
        self._logger.setLevel(LOGGING_LEVEL)
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

    def send(self, json_msg, dest):
        """
        Encodes and sends json data to the given destination.
        Note that this does NOT use the socket this listener listens on.
        Returns success or failure.

        Arguments:
        json_msg -- the json data to send;
        dest -- a tuple of address and port to send to
        """
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            mesg = json.dumps(json_msg).encode()
            length = len(mesg)
            for _ in range(MAX_TRIES):
                try:
                    sock.connect(dest)
                    res = sock.send(mesg)
                    sock.close()
                    if res == length:
                        # Successfully sent the correct amount of data
                        return True
                except:
                    return False
        return False

    def listen(self):
        """
        Listens for incoming TCP messages.

        Returns the decoded json data and the sender if there is a message.
        """
        try:
            self._socket.listen()
            conn, addr = self._socket.accept()

            msg_data = ""

            while True:
                res = conn.recv(BUFFER_SIZE)
                if res:
                    msg_data += res.decode()
                    continue
                else:
                    break

            data = json.loads(msg_data)
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
                dispatcher.send(
                    signal=ON_TCP_MESSAGE,
                    sender=self,
                    data=data,
                    addr=addr,
                )

        self._logger.debug("Shutting down.")
        self.close()
