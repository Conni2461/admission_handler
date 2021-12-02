import socket
from util import broadcast
from constants import BROADCAST_PORT

if __name__ == '__main__':
    MY_HOST = socket.gethostname()
    MY_IP = socket.gethostbyname(MY_HOST)

    # Send broadcast message
    message = 'hello sent a broadcast'
    broadcast(BROADCAST_PORT, message)
