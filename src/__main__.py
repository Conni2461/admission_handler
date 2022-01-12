import argparse
import logging

from src.utils.signals import ON_ENTRY_REQUEST

parser = argparse.ArgumentParser(description="No help")
parser.add_argument("--server", action="store_true", default=False)
parser.add_argument("--client", action="store_true", default=False)

args = parser.parse_args()

logging.basicConfig(level=logging.DEBUG, format="%(levelname)s %(name)s - %(message)s")

if args.server:
    from .server.server import Server
    from .utils.util import RepeatTimer

    server = Server()

    def send():
        server._rom_listener.send({"msg": "test"})

    #RepeatTimer(5, send).start()
    server.run()
elif args.client:
    from .client.client import Client
    from louie import dispatcher
    number = 0
    Client(number).run()
else:
    parser.print_help()
