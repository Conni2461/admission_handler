import socket

from ..utils.constants import BROADCAST_PORT
from ..utils.constants import BUFFER_SIZE
from ..utils.constants import CLIENT_BASE_PORT
from ..utils.util import broadcast


class Client:
    # TODO: broadcast at intervals until a response arrives, connect to server, on input(), send a request
    def __init__(self, number):
        self.entries = 0
        # TODO: switch to uuids as well?
        self.port = CLIENT_BASE_PORT + number

    def run(self):
        self.client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        # TODO: Verify that the local IP is the one to bind to
        self.client.bind(("127.0.0.1", self.port))

        # Send broadcast message until a server responds
        while self.server == None:
            broadcast(BROADCAST_PORT, "Lfg")
            # TODO: listen -> accept from https://wiki.python.org/moin/TcpCommunication
            self.client.listen(1)
            self.client.accept()

        # End of Setup, wait for user input to send requests
        while True:
            input("Press Enter to send a request.")
            self.server.send(self.entries)
            data = self.client.recv(BUFFER_SIZE)
