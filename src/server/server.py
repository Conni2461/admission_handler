import datetime
import json
import logging
import os
import sys
import uuid

from louie import dispatcher

from ..utils.constants import (ACCEPT_SERVER, BROADCAST_PORT, ELECTION_MESSAGE,
                               HEARTBEAT, HEARTBEAT_TIMEOUT, IDENT_CLIENT,
                               IDENT_SERVER, MAX_TRIES, SHUTDOWN_SERVER,
                               UPDATE_GROUP_VIEW, State)
from ..utils.listeners import TCPListener, UDPListener
from ..utils.signals import ON_BROADCAST_MESSAGE, ON_TCP_MESSAGE
from ..utils.util import CircularList, CustomLogger, RepeatTimer, broadcast

logging.basicConfig(format="%(levelname)s:%(message)s", level=logging.DEBUG)


class Server:
    def __init__(self):
        self._state = State.PENDING
        self._tcp_listener = TCPListener()
        self._udp_listener = UDPListener()
        self._uuid = str(uuid.uuid4())
        self._group_view = dict()
        self._current_leader = None
        self._logger = logging.getLogger(f"Server {self._uuid}")
        self._logger.setLevel(logging.DEBUG)
        self._participating = False
        self._heartbeats = {}
        self._heartbeat_timer = None

        dispatcher.connect(self._on_tcp_msg, signal=ON_TCP_MESSAGE, sender=self._tcp_listener)
        dispatcher.connect(
            self._on_udp_msg, signal=ON_BROADCAST_MESSAGE, sender=self._udp_listener
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
                    self._logger.debug(f"I have been accepted by leader {self._current_leader}. Group view has been populated.")
                    self._set_leader(False)
                    break

        if self._state == State.PENDING:
            self._set_leader()
            self._group_view[self._uuid] = (
                self._tcp_listener.address,
                self._tcp_listener.port,
            )

        self._logger.debug(f"In Request Join: {self._state}, {self._group_view}")
        self._udp_listener.start()

    def _on_udp_msg(self, data=None, addr=None):
        if self._state == State.LEADER:
            if data["intention"] == IDENT_SERVER and data["uuid"] != self._uuid:
                self._group_view[data["uuid"]] = (data["address"], data["port"])

                welcome_msg = {
                    "intention": ACCEPT_SERVER,
                    "leader": f"{self._uuid}",
                    "group_view": self._group_view
                }

                self._tcp_listener.send(json.dumps(welcome_msg), self._group_view[data["uuid"]])
                self._logger.debug("Received server join request from {}".format((data["address"], data["port"])))

                self._logger.debug("New group view is: {}".format(self._group_view))

                self._logger.debug("Distributing group view.")
                self._distribute_group_view()

                self._logger.debug("Checking election required.")
                if self._election_required():
                    self._logger.debug("Election is required, starting election.")
                    self._start_election()
                else:
                    self._logger.debug("No election required.")

            elif data["intention"] == IDENT_CLIENT:
                self._logger.debug(f"TODO: {data}")
            else:
                # TODO: handle other broadcasts?
                if (data["uuid"] != self._uuid):
                    # TODO: maybe ignore udp msg uuids that we sent ourselves
                    self._logger.debug(f"How did we get here?\n {data}")
        else:
            self._logger.debug(f"Received broadcast message: {data} from {addr}")

    def _start_election(self):
        neighbor = self._get_neighbor()
        election_msg = {
            "intention": ELECTION_MESSAGE,
            "mid": self._uuid,
            "is_leader": False
        }
        self._logger.debug(f"Starting election, sending election message to {neighbor}")
        self._send_election_message(json.dumps(election_msg))

    def _election_required(self):
        return self._uuid != self._get_ring()[0]

    def _get_neighbor(self, uuid=None):
        ring = self._get_ring()
        idx = ring.index(uuid or self._uuid)
        return ring.next(idx)

    def _get_ring(self):
        return CircularList(sorted([member for member in self._group_view.keys()], reverse=True))

    def _set_leader(self, state=True):
        if state:
            self._state = State.LEADER
            if self._heartbeat_timer is not None:
                self._heartbeat_timer.cancel()
            self._heartbeat_timer = RepeatTimer(HEARTBEAT_TIMEOUT + 5, self._check_heartbeats)
            self._heartbeat_timer.start()
        else:
            if self._heartbeat_timer is not None:
                self._heartbeat_timer.cancel()
            self._heartbeat_timer = RepeatTimer(HEARTBEAT_TIMEOUT, self._send_heartbeat)
            self._heartbeat_timer.start()

    def _send_heartbeat(self):
        msg = {
            "intention": HEARTBEAT,
            "uuid": f"{self._uuid}"
        }
        self._tcp_listener.send(json.dumps(msg), self._group_view[self._current_leader])

    def _check_heartbeats(self):
        now = datetime.datetime.now().timestamp()
        for uuid in self._group_view.keys():
            if uuid == self._uuid:
                continue
            latest_beat = self._heartbeats.get(uuid)
            if latest_beat:
                diff = latest_beat - now
                if diff > HEARTBEAT_TIMEOUT:
                    self._logger.debug(f"Node {uuid} has timed out.")
            else:
                self._logger.debug(f"Node {uuid} does not appear to be in group view.")

    def _on_received_heartbeat(self, data):
        uuid = data["uuid"]
        self._logger.debug(f"Recevied heartbeat from {uuid}.")
        if uuid in self._group_view:
            self._heartbeats[data["uuid"]] = datetime.datetime.now().timestamp()
        else:
            self._logger.warning(f"Received heartbeat from {uuid} who is not in group view.")

    def _send_election_message(self, message):
        prev_neighbor = None
        success = False
        while not success:
            neighbor = self._get_neighbor(prev_neighbor)
            if neighbor == self._uuid:
                self._logger.error("Could not find any available neighbors.")
                success = True
            prev_neighbor = neighbor
            try:
                self._tcp_listener.send(message, self._group_view[neighbor])
                success = True
            except ConnectionRefusedError as e:
                self._logger.warning(e)

    def _on_election_message(self, data):
        self._logger.debug(f"Received Election Message from {data['mid']}")
        neighbor = self._get_neighbor()

        if data["is_leader"]:
            self._logger.debug(f"Message is a leader message, setting {data['mid']} to leader.")
            self._current_leader = data["mid"]

            if self._participating:
                self._participating = False
                if self._state == State.LEADER:
                    self._set_leader(False)
                self._state = State.MEMBER
                self._logger.debug(f"Relaying leader message to {neighbor}.")
                self._send_election_message(json.dumps(data))
            else:
                self._set_leader()
                self._logger.debug("Received my own leader message, will terminate the election.")
            return

        if data["mid"] < self._uuid and not self._participating:
            self._logger.debug("Currently not participating, joining election.")
            data["mid"] = self._uuid
            data["is_leader"] = False

            self._participating = True
            self._logger.debug(f"Sending election message on to {neighbor}.")
            self._send_election_message(json.dumps(data))

        elif data["mid"] > self._uuid:
            self._logger.debug(f"UUID is smaller than previous neighbor, relaying message to {neighbor}.")
            self._participating = True
            self._send_election_message(json.dumps(data))

        elif data["mid"] == self._uuid:
            self._logger.debug(f"Received my own election message, declaring myself leader and sending leader message to {neighbor}")
            self._current_leader = self._uuid
            data["mid"] = self._uuid
            data["is_leader"] = True
            self._participating = False
            self._send_election_message(json.dumps(data))

    def _distribute_group_view(self):
        for uuid, address in self._group_view.items():
            if uuid != self._uuid:
                data = {
                    "intention": UPDATE_GROUP_VIEW,
                    "group_view": self._group_view
                }
                try:
                    self._tcp_listener.send(json.dumps(data), address)
                except ConnectionRefusedError as e:
                    self._logger.warning(e)

    def _on_received_grp_view(self, data):
        group_view = {}
        for key, value in data["group_view"].items():
            group_view[key] = tuple(value)
        self._group_view = group_view
        self._logger.debug(f"Received updated group view with {len(list(self._group_view.keys()))} items.")

    def _on_tcp_msg(self, data=None, addr=None):
        res = json.loads(data)
        if res["intention"] == UPDATE_GROUP_VIEW:
            self._on_received_grp_view(res)
        elif res["intention"] == ELECTION_MESSAGE:
            self._on_election_message(res)
        elif res["intention"] == SHUTDOWN_SERVER:
            self._group_view.pop(res["uuid"])
            self._heartbeats.pop(res["uuid"])
            self._logger.debug(f"Received shutdown message from sever {res['uuid']}. Removing from group view.")
            self._distribute_group_view()
        elif res["intention"] == HEARTBEAT:
            self._on_received_heartbeat(res)

    def _shut_down(self):
        self._logger.info("Shutting down.")
        leader_address = self._group_view.get(self._current_leader)

        msg = {
            "intention": SHUTDOWN_SERVER,
            "uuid": f"{self._uuid}"
        }

        self._tcp_listener.join()
        self._udp_listener.join()
        self._heartbeat_timer.cancel()

        if leader_address and self._current_leader != self._uuid:
            self._tcp_listener.send(json.dumps(msg), leader_address)
        else:
            broadcast(BROADCAST_PORT, msg)

    def run(self):

        self._request_join()
        self._tcp_listener.start()

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
