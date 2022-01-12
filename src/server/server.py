import datetime
import json
import logging
import os
import sys
import uuid

from louie import dispatcher

from ..utils.constants import (ACCEPT_CLIENT, ACCEPT_ENTRY, ACCEPT_SERVER, BROADCAST_PORT, DENY_ENTRY, ELECTION_MESSAGE,
                               HEARTBEAT, HEARTBEAT_TIMEOUT, IDENT_CLIENT,
                               IDENT_SERVER, MAX_ENTRIES, MAX_TIMEOUTS, MAX_TRIES, REQUEST_ENTRY,
                               SHUTDOWN_SERVER, UPDATE_GROUP_VIEW, State)
from ..utils.listeners import ROMulticast, TCPListener, UDPListener
from ..utils.signals import (ON_BROADCAST_MESSAGE, ON_MULTICAST_MESSAGE,
                             ON_TCP_MESSAGE)
from ..utils.util import CircularList, CustomLogger, RepeatTimer, broadcast

logging.basicConfig(format="%(levelname)s:%(message)s", level=logging.DEBUG)


class Server:
    def __init__(self):
        self._state = State.PENDING
        self._tcp_listener = TCPListener()
        self._udp_listener = UDPListener()
        self._uuid = str(uuid.uuid4())
        self._group_view = dict()
        self._rom_listener = ROMulticast(str(self._uuid), self._group_view)
        self._current_leader = None
        self._logger = logging.getLogger(f"Server {self._uuid}")
        self._logger.setLevel(logging.DEBUG)
        self._participating = False
        self._heartbeats = {}
        self._heartbeat_timer = None

        self._setup_connections()

    def _setup_connections(self):
        dispatcher.connect(
            self._on_tcp_msg, signal=ON_TCP_MESSAGE, sender=self._tcp_listener
        )
        dispatcher.connect(
            self._on_udp_msg, signal=ON_BROADCAST_MESSAGE, sender=self._udp_listener
        )
        dispatcher.connect(
            self._on_rom_msg, signal=ON_MULTICAST_MESSAGE, sender=self._rom_listener
        )

    # network message handler methods -----------------------------------------

    def _on_udp_msg(self, data=None, addr=None):
        if data.get("uuid") == self._uuid:
            return

        if (data["intention"] == IDENT_SERVER) and (self._state == State.LEADER):
            self._register_server(data)

        elif data["intention"] == IDENT_CLIENT:
            self._register_client(data, addr)

        elif data["intention"] == SHUTDOWN_SERVER:
            add = "(leader)" if data["uuid"] == self._current_leader else ""
            self._logger.debug(
                f"Received shutdown message from {data['uuid']}{add}, will start an election."
            )
            self._start_election()

        else:
            self._logger.debug(f"Received broadcast message: {data} from {addr}")

    def _on_tcp_msg(self, data=None, addr=None):
        res = json.loads(data)
        if res["intention"] == UPDATE_GROUP_VIEW:
            self._on_received_grp_view(res)
        elif res["intention"] == ELECTION_MESSAGE:
            self._on_election_message(res)
        elif res["intention"] == SHUTDOWN_SERVER:
            self._group_view.pop(res["uuid"])
            self._heartbeats.pop(res["uuid"])
            self._logger.debug(
                f"Received shutdown message from sever {res['uuid']}. Removing from group view."
            )
            self._distribute_group_view()
        elif res["intention"] == HEARTBEAT:
            self._on_received_heartbeat(res)
        elif res["intention"] == REQUEST_ENTRY:
            self._on_request_entry(res, addr)

    def _on_rom_msg(self, data=None):
        self._logger.debug(f"TODO: Do something with rom message: {data}")

    # group view methods ------------------------------------------------------

    def _distribute_group_view(self):
        self._logger.debug(
            f"Distributing group view to {len(self._group_view.keys())-1} members."
        )
        self._rom_listener.set_group_view(self._group_view)
        for uuid, address in self._group_view.items():
            if uuid != self._uuid:
                data = {"intention": UPDATE_GROUP_VIEW, "group_view": self._group_view}
                try:
                    self._tcp_listener.send(json.dumps(data), address)
                except ConnectionRefusedError as e:
                    self._logger.warning(f"Could not send group view to: {uuid} - {e}.")

    def _on_received_grp_view(self, data):
        group_view = {}
        for key, value in data["group_view"].items():
            group_view[key] = tuple(value)
        for new_member in set(group_view.keys()) - set(self._group_view.keys()):
            self._rom_listener.register_new_member(new_member)
        self._group_view = group_view
        self._rom_listener.set_group_view(self._group_view)
        self._logger.debug(
            f"Received updated group view with {len(list(self._group_view.keys()))} items."
        )

    def _request_join(self):
        mes = {
            "intention": IDENT_SERVER,
            "uuid": f"{self._uuid}",
            "address": self._tcp_listener.address,
            "port": self._tcp_listener.port,
        }

        self._logger.debug("Requesting join.")
        broadcast(BROADCAST_PORT, mes)

        for _ in range(MAX_TRIES):
            res, add = self._tcp_listener.listen(1)
            if res is not None:
                data = json.loads(res)
                if data.get("intention") == ACCEPT_SERVER:
                    self._state = State.MEMBER
                    self._current_leader = data.get("leader")
                    self._group_view = data.get("group_view")
                    self._logger.debug(
                        f"I have been accepted by leader {self._current_leader}. Group view has been populated."
                    )
                    self._set_leader(False)
                    self._rom_listener.sync_state(
                        json.loads(data.get("rnumbers")),
                        json.loads(data.get("deliver_queue")),
                    )
                    break

        if self._state == State.PENDING:
            self._logger.debug(
                "Looks like there is no leader, declaring myself leader."
            )
            self._set_leader(True)
            self._group_view[self._uuid] = (
                self._tcp_listener.address,
                self._tcp_listener.port,
            )
            self._rom_listener.set_group_view(self._group_view)

        self._logger.debug(f"In Request Join: {self._state}, {self._group_view}")

    def _register_server(self, data):
        self._group_view[data["uuid"]] = (data["address"], data["port"])

        welcome_msg = {
            "intention": ACCEPT_SERVER,
            "leader": f"{self._uuid}",
            "group_view": self._group_view,
            "rnumbers": json.dumps(self._rom_listener._rnumbers),
            "deliver_queue": json.dumps(self._rom_listener._deliver_queue),
            # "buisness_data": TODO send the current state of the system to the new member
        }

        self._rom_listener.register_new_member(data["uuid"])
        self._tcp_listener.send(
            json.dumps(welcome_msg), self._group_view[data["uuid"]]
        )
        self._logger.debug(
            "Received server join request from {}".format(
                (data["address"], data["port"])
            )
        )

        self._logger.debug("New group view is: {}".format(self._group_view))

        self._heartbeats[data["uuid"]] = {"ts": datetime.datetime.now().timestamp(), "strikes": 0}
        self._distribute_group_view()

        self._logger.debug("Checking election required.")
        if self._election_required():
            self._logger.debug("Election is required, starting election.")
            self._start_election()
        else:
            self._logger.debug("No election required.")

    # election methods --------------------------------------------------------

    def _start_election(self):
        neighbor = self._get_neighbor()
        election_msg = {
            "intention": ELECTION_MESSAGE,
            "mid": self._uuid,
            "is_leader": False,
        }
        self._logger.debug(f"Starting election, sending election message to {neighbor}")
        self._participating = True
        self._send_election_message(election_msg)

    def _election_required(self):
        return self._uuid != self._get_ring()[0]

    def _get_neighbor(self, uuid=None):
        ring = self._get_ring()
        idx = ring.index(uuid or self._uuid)
        return ring.next(idx)

    def _get_ring(self):
        return CircularList(
            sorted([member for member in self._group_view.keys()], reverse=True)
        )

    def _send_election_message(self, message):
        prev_neighbor = None
        success = False
        while not success:
            neighbor = self._get_neighbor(prev_neighbor)
            if neighbor == self._uuid:
                self._logger.warning(
                    "Could not find any available neighbors. Calling my own method."
                )
                self._on_election_message(message)
                success = True
                continue
            prev_neighbor = neighbor
            try:
                self._tcp_listener.send(json.dumps(message), self._group_view[neighbor])
                success = True
            except ConnectionRefusedError as e:
                self._logger.warning(
                    f"Could not send election message to {neighbor}: {e}."
                )

    def _on_election_message(self, data):
        self._logger.debug(f"Received Election Message from {data['mid']}")
        neighbor = self._get_neighbor()

        if data["is_leader"]:
            self._logger.debug(
                f"Message is a leader message, setting {data['mid']} to leader."
            )
            self._current_leader = data["mid"]

            if self._participating:
                self._participating = False
                if self._state == State.LEADER:
                    self._set_leader(False)
                self._state = State.MEMBER
                self._logger.debug(f"Relaying leader message to {neighbor}.")
                self._send_election_message(data)
            else:
                self._set_leader(True)
                self._distribute_group_view()
                self._logger.debug(
                    "Received my own leader message, will terminate the election."
                )
            return

        if data["mid"] < self._uuid and not self._participating:
            self._logger.debug("Currently not participating, joining election.")
            data["mid"] = self._uuid
            data["is_leader"] = False

            self._participating = True
            self._logger.debug(f"Sending election message on to {neighbor}.")
            self._send_election_message(data)

        elif data["mid"] > self._uuid:
            self._logger.debug(
                f"UUID is smaller than previous neighbor, relaying message to {neighbor}."
            )
            self._participating = True
            self._send_election_message(data)

        elif data["mid"] == self._uuid:
            self._logger.debug(
                f"Received my own election message, declaring myself leader and sending leader message to {neighbor}"
            )
            self._current_leader = self._uuid
            data["mid"] = self._uuid
            data["is_leader"] = True
            self._participating = False
            self._send_election_message(data)

    # heartbeat methods -------------------------------------------------------

    def _send_heartbeat(self):
        if not self._participating:
            msg = {"intention": HEARTBEAT, "uuid": f"{self._uuid}"}
            try:
                self._tcp_listener.send(
                    json.dumps(msg), self._group_view[self._current_leader]
                )
            except ConnectionRefusedError:
                self._logger.warning(
                    "Leader seems to be offline, starting new election."
                )
                self._start_election()
        else:
            self._logger.debug("Not sending heartbeat because I am participating in an election.")

    def _check_heartbeats(self):
        self._logger.debug("Checking heartbeats.")
        now = datetime.datetime.now().timestamp()
        remove = []
        for uuid in self._group_view.keys():
            if uuid == self._uuid:
                continue
            latest_beat = self._heartbeats.get(uuid, {}).get("ts")
            if latest_beat:
                diff = now - latest_beat
                if diff > HEARTBEAT_TIMEOUT:
                    self._logger.debug(f"Node {uuid} has timed out.")
                    self._heartbeats[uuid]["strikes"] = self._heartbeats[uuid]["strikes"] +1
                    if self._heartbeats[uuid]["strikes"] >= MAX_TIMEOUTS:
                        self._logger.debug(f"Node {uuid} has timed out twice in a row. Removing.")
                        remove.append(uuid)
            else:
                self._logger.debug(
                    f"Node {uuid} does not appear to be in group view. Removing."
                )
                remove.append(uuid)

        if remove:
            for uid in remove:
                self._group_view.pop(uid)
                self._heartbeats.pop(uid)
            self._distribute_group_view()

    def _on_received_heartbeat(self, data):
        if data['uuid'] in self._group_view:
            self._logger.debug(f"Received heartbeat from {data['uuid']}.")
            self._heartbeats[data["uuid"]] = {"ts": datetime.datetime.now().timestamp(), "strikes": 0}
        else:
            self._logger.warning(
                f"Received heartbeat from {data['uuid']} who is not in group view."
            )

    # other methods -----------------------------------------------------------

    def _set_leader(self, state=True):
        if state:
            self._state = State.LEADER
            if self._heartbeat_timer is not None:
                self._heartbeat_timer.cancel()
            self._heartbeat_timer = RepeatTimer(
                HEARTBEAT_TIMEOUT + 5, self._check_heartbeats
            )
            self._heartbeat_timer.start()
        else:
            if self._heartbeat_timer is not None:
                self._heartbeat_timer.cancel()
            self._heartbeat_timer = RepeatTimer(HEARTBEAT_TIMEOUT, self._send_heartbeat)
            self._heartbeat_timer.start()

    def _register_client(self, data, addr):
        mes = {
            "intention": ACCEPT_CLIENT,
        }
        self._logger.info(data)
        self._tcp_listener.send(mes, (data['address'],data['port']))

    def _on_request_entry(self, res, addr):
        mes = {"uuid": f"{self.uuid}"}
        if self._grant_entry():
            self._logger.info(f"A client with No. {res['number']} and UUID {res['uuid']} requests entry. Accepting.")
            mes["intention"] =  ACCEPT_ENTRY
            mes["entries"] = self.entries
        else:
            self._logger.info(f"A client with No. {res['number']} and UUID {res['uuid']} requests entry. Denied, we are full.")
            mes["intention"] = DENY_ENTRY
        self._tcp_listener.send(mes, addr)

    def _grant_entry(self):
        #TODO lock remote entries
        if self.entries == None:
            self.entries = 0
        if self.entries < MAX_ENTRIES:
            #TODO use remote entries
            self.entries += 1
            return True
        else:
            return False

    # process methods ---------------------------------------------------------

    def _shut_down(self):
        self._logger.info("Shutting down.")
        leader_address = self._group_view.get(self._current_leader)

        msg = {"intention": SHUTDOWN_SERVER, "uuid": f"{self._uuid}"}

        self._tcp_listener.join()
        self._udp_listener.join()
        #TODO currently doesn't work
        self._rom_listener.join()
        self._logger.info("All listeners shut down, canceling heartbeat timer.")
        self._heartbeat_timer.cancel()

        if leader_address and self._current_leader != self._uuid:
            self._tcp_listener.send(json.dumps(msg), leader_address)
        else:
            broadcast(BROADCAST_PORT, msg)

    def run(self):

        self._request_join()
        self._tcp_listener.start()
        self._udp_listener.start()
        self._rom_listener.start()

        try:
            while True:
                pass
        except KeyboardInterrupt:
            self._logger.debug("Interrupted.")
            self._shut_down()
            try:
                sys.exit(0)
            except SystemExit:
                os._exit(0)
