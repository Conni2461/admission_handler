from enum import Enum

BROADCAST_IP = "192.168.0.255"
BROADCAST_PORT = 5973
MULTICAST_IP = "224.1.1.1"
MULTICAST_PORT = 5007
WINDOWS_IP = "127.0.0.1"
IDENT_SERVER = "IDServer"
IDENT_CLIENT = "IDClient"
REQUEST_ENTRY = "ClientEntryRequest"
SHUTDOWN_SERVER = "ShutdownServer"
SHUTDOWN_SYSTEM = "ShutdownSystem"
UPDATE_ENTRIES = "UpdateEntries"
UPDATE_GROUP_VIEW = "UpdateGV"
ACCEPT_SERVER = "AcceptServer"
ACCEPT_CLIENT = "AcceptClient"
ACCEPT_ENTRY = "AcceptEntry"
DENY_ENTRY = "DenyEntry"
REVERT_ENTRY = "RevertEntry"
ELECTION_MESSAGE = "ElectionMessage"
HEARTBEAT = "Heartbeat"
TIMEOUT = 0.1
MAX_TRIES = 3
MAX_ENTRIES = 100
BUFFER_SIZE = 1024
MAX_MSG_BUFF_SIZE = 50
HEARTBEAT_TIMEOUT = 10  # seconds
MAX_TIMEOUTS = 2

class State(Enum):
    PENDING = 0
    LEADER = 1
    MEMBER = 2


class Purpose(Enum):
    REAL_MSG = 0
    PROP_SEQ = 1
    FIN_SEQ = 2
    NACK = 3
