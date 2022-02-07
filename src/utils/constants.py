import logging
from enum import Enum

BROADCAST_IP = "192.168.0.255"
BROADCAST_PORT = 5973
MULTICAST_IP = "224.1.1.1"
MULTICAST_PORT = 5007
TIMEOUT = 0.1
MAX_TRIES = 3
MAX_ENTRIES = 20
BUFFER_SIZE = 1024
MAX_MSG_BUFF_SIZE = 50
HEARTBEAT_TIMEOUT = 10  # seconds
MAX_TIMEOUTS = 2
LOGGING_LEVEL = logging.INFO

class State(Enum):
    PENDING = 0
    LEADER = 1
    MEMBER = 2

class Intention(Enum):
    IDENT_SERVER = 0
    IDENT_CLIENT = 1
    SHUTDOWN_SERVER = 2
    REQUEST_ACTION = 3
    SHUTDOWN_SYSTEM = 4
    UPDATE_ENTRIES = 5
    UPDATE_GROUP_VIEW = 6
    ACCEPT_SERVER = 7
    ACCEPT_CLIENT = 8
    ACCEPT_ENTRY = 9
    DENY_ENTRY = 10
    REVERT_ENTRY = 11
    ELECTION_MESSAGE = 12
    HEARTBEAT = 13
    PING = 14
    MONITOR_MESSAGE = 15
    OM = 16
    OM_RESULT = 17
    REQUEST_EXIT = 18
    LOCK = 19
    UNLOCK = 20
    NOT_LEADER = 21
    CHOOSE_SERVER = 22
    SHUTDOWN_CLIENT = 23
    WAIT_FOR_LEADER = 24

class LockState(Enum):
    OPEN = 0
    MINE = 1
    CLOSED = 2

class Purpose(Enum):
    REAL_MSG = 0
    PROP_SEQ = 1
    FIN_SEQ = 2
    NACK = 3
    STOP = 4
    RESUME = 5
