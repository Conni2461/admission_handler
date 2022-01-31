import argparse
import logging
from random import randint

parser = argparse.ArgumentParser(description="No help")
parser.add_argument("--server", action="store_true", default=False)
parser.add_argument("--client", action="store_true", default=False)
parser.add_argument("--monitor", action="store_true", default=False)

args = parser.parse_args()

logging.basicConfig(level=logging.DEBUG, format="%(levelname)s %(name)s - %(message)s")

if args.server:
    from .server.server import Server
    from .utils.common import RepeatTimer

    server = Server()

    #def send():
    #   server._rom_handler.send({"msg": "test"})

    #RepeatTimer(5, send).start()
    server.run()
elif args.client:
    from .client.client import Client

    #from louie import dispatcher
    #TODO do this better, currently only acceptable for testing
    number = randint(1,100)
    Client(number).run()
elif args.monitor:
    from .utils import monitor
    monitor.start_monitor()
else:
    parser.print_help()
