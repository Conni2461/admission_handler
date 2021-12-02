import socket
from constants import BROADCAST_PORT
import sys

class Listener:
    def __init__(self):
        self.listen_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        # Set the socket to broadcast and enable reusing addresses
        if sys.platform == "win32":
            self.listen_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        else:
            self.listen_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        self.listen_socket.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        # Bind socket to address and port
        self.listen_socket.bind(("", BROADCAST_PORT))

    def run(self):
        print("Listening to broadcast messages")
        while True:
            data, addr = self.listen_socket.recvfrom(1024)
            if data:
                print("Received broadcast message:", data.decode(), addr)



if __name__ == '__main__':
    listener = Listener()
    listener.run()
