import socket

from ..utils.constants import BROADCAST_PORT
from ..utils.util import broadcast


class Client:
    def __init__(self):
        MY_HOST = socket.gethostname()
        MY_IP = socket.gethostbyname(MY_HOST)

    def run(self):
        # Send broadcast message
        message = 'hello sent a broadcast'
        broadcast(BROADCAST_PORT, message)
