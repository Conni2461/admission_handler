import argparse

parser = argparse.ArgumentParser(description='No help')
parser.add_argument('--server', action='store_true', default=False)
parser.add_argument('--client', action='store_true', default=False)

args = parser.parse_args()

if args.server:
    from .server.server import Server
    Server().run()
elif args.client:
    from .client.client import Client
    Client().run()
else:
    parser.print_help()
