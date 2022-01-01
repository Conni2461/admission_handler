import argparse
import logging

parser = argparse.ArgumentParser(description='No help')
parser.add_argument('--server', action='store_true', default=False)
parser.add_argument('--client', action='store_true', default=False)
parser.add_argument('--rom', action='store_true', default=False)

args = parser.parse_args()

logging.basicConfig(level=logging.DEBUG,
                    format='%(levelname)s %(name)s - %(message)s')

if args.server:
    from .server.server import Server
    server = Server()
    server.run()
elif args.client:
    from .client.client import Client
    Client().run()
elif args.rom:
    import uuid
    import sys
    from .utils.listeners import ROMulticast
    from louie import dispatcher
    from .utils.signals import ON_MULTICAST_MESSAGE

    def on_multi_msg(data=None):
        print(data)


    listener = ROMulticast(str(uuid.uuid4()))
    dispatcher.connect(on_multi_msg, signal=ON_MULTICAST_MESSAGE, sender=listener)
    listener.start()

    for line in sys.stdin:
        listener.send({ "msg": line.strip() })
else:
    parser.print_help()
