import datetime
import json
import logging
import math
import os
import queue
import sys
import time
from copy import deepcopy
from queue import Queue
from uuid import uuid4

from src.utils.broadcast_handler import BroadcastHandler
from src.utils.byzantine import (ByzantineLeaderCache, ByzantineMemberCache,
                                 ByzantineStates)
from src.utils.rom_handler import ROMulticastHandler
from src.utils.tcp_handler import TCPHandler

from ..utils.common import (CircularList, Invokeable, RepeatTimer,
                            get_hostname, get_real_ip)
from ..utils.constants import (HEARTBEAT_TIMEOUT, LOGGING_LEVEL, MAX_ENTRIES,
                               MAX_TIMEOUTS, MAX_TRIES, Intention, LockState,
                               State)
from ..utils.signals import (ON_BROADCAST_MESSAGE, ON_HEARTBEAT_TIMEOUT,
                             ON_MULTICAST_MESSAGE, ON_TCP_MESSAGE)

logging.basicConfig(format="%(levelname)s:%(message)s", level=logging.DEBUG)

class Server:

    QUEUE = queue.SimpleQueue()

    def __init__(self):
        """Set up handlers, uuid etc."""
        self._state = State.PENDING
        self._uuid = str(uuid4())
        self._group_view = dict()
        self._current_leader = None
        self._participating = False
        self._heartbeats = {}
        self._heartbeat_timer = None

        self._my_ip = get_real_ip()
        self._my_hostname = get_hostname()

        self._tcp_handler = TCPHandler(self.QUEUE)
        self._broadcast_handler = BroadcastHandler(self.QUEUE)
        self._rom_handler = ROMulticastHandler(str(self._uuid), self._group_view, self.QUEUE)

        self._logger = logging.getLogger(f"Server {self._uuid}")
        self._logger.setLevel(LOGGING_LEVEL)

        self._clients = dict()
        self._requests = Queue()
        self._lock = LockState.OPEN
        self._entries = 0

        self._byzantine_leader_cache = None
        self._byzantine_member_cache = None
        self._byzantine_history = {}

    # network message handler methods -----------------------------------------

    def _on_udp_msg(self, data=None, addr=None):
        if data == None:
            self._logger.warn("Got called for an empty Broadcast message!")
            return
        if data.get("uuid") == self._uuid:
            return
        if (data["intention"] == str(Intention.IDENT_SERVER)) and (self._state == State.LEADER):
            if (self._byzantine_leader_cache is not None) or self._participating:
                wait_for = {
                    "intention": str(Intention.TRY_AGAIN)
                }
                if not self._tcp_handler.send(wait_for, self._group_view[data["uuid"]]):
                    self._logger.warn("Wasn't able to answer with a wait for message")
            else:
                self._register_server(data)
        elif data["intention"] == str(Intention.IDENT_CLIENT):
            self._register_client(data)
        elif data["intention"] == str(Intention.SHUTDOWN_SERVER):
            add = "(leader)" if data["uuid"] == self._current_leader else ""
            self._logger.debug(
                f"Received shutdown message from {data['uuid']}{add}, will start an election."
            )
            self._start_election()
        elif data["intention"] == str(Intention.MONITOR_MESSAGE):
            pass
        elif data["intention"] == str(Intention.RUN_BYZ) and (self._state == State.LEADER):
            self._logger.info("Got byzantine request.")
            if self._can_byzantine():
                    self._rom_handler.pause()
                    self._start_byzantine()
        else:
            self._logger.debug(f"Received broadcast message: {data}")

    def _on_tcp_msg(self, data=None, addr=None):
        if data == None:
            self._logger.warn("Got called for an empty TCP message!")
            return
        if data["intention"] == str(Intention.UPDATE_GROUP_VIEW):
            self._on_received_grp_view(data)
        elif data["intention"] == str(Intention.ELECTION_MESSAGE):
            self._on_election_message(data)
        elif data["intention"] == str(Intention.SHUTDOWN_SERVER):
            try:
                self._group_view.pop(data["uuid"])
            except:
                pass
            try:
                self._heartbeats.pop(data["uuid"])
            except:
                pass
            self._logger.debug(
                f"Received shutdown message from sever {data['uuid']}. Removing from group view."
            )
            self._distribute_group_view()
        elif data["intention"] == str(Intention.HEARTBEAT):
            self._on_received_heartbeat(data)
        elif data["intention"] == str(Intention.CHOOSE_SERVER):
            self._clients[data["uuid"]] = (data['address'],data['port'])
            self._logger.info("Was chosen by client with uuid " + data["uuid"])
        elif data["intention"] == str(Intention.SHUTDOWN_CLIENT):
            self._clients.pop(data["uuid"])
            self._logger.info("Client "+data["uuid"]+" shut down, removed it from client list.")
        elif data["intention"] == str(Intention.REQUEST_ACTION):
            self._on_request_action(data)
        elif data["intention"] == str(Intention.OM):
            if "v" not in data:
                self._stop_byzantine(data)
            else:
                self._on_byzantine_om(data)
        elif data["intention"] == str(Intention.OM_RESTART):
                self._start_byzantine(data["id"])
        elif data["intention"] == str(Intention.NOT_LEADER):
            self._request_join(rejoin=True)
        elif data["intention"] == str(Intention.MANUAL_VALUE_OVERRIDE):
            self._entries = data["value"]
            self._logger.info(f"Manually changed entires to: {data['value']}")
            self._promote_monitoring_data()
        else:
            self._logger.warning(f"Got message I can not process: {data}")
    def _on_rom_msg(self, data=None):
        if data == None:
            self._logger.warn("Got called for an empty ROM message!")
            return
        elif data["intention"] == str(Intention.OM_RESULT):
            self._entries = data["result"]
        elif data["intention"] == str(Intention.LOCK) or data["intention"] == str(Intention.UNLOCK):
            self._update_lock(data)
        elif data["intention"] == str(Intention.UPDATE_ENTRIES) and data["uuid"] != self._uuid:
            self._entries = data["entries"]
            self._logger.info("Current Entries: " + str(self._entries) + " of " + str(MAX_ENTRIES))
            self._update_client_entries()
        else:
            self._logger.debug(f"TODO: Do something with rom message: {data}")

        self._promote_monitoring_data()

    # group view methods ------------------------------------------------------

    def _distribute_group_view(self):
        self._logger.debug(
            f"Distributing group view to {len(self._group_view.keys())-1} members."
        )
        self._rom_handler.set_group_view(self._group_view)
        for uuid, address in self._group_view.items():
            if uuid != self._uuid:
                data = {"intention": str(Intention.UPDATE_GROUP_VIEW), "group_view": self._group_view}
                if not self._tcp_handler.send(data, address):
                    self._logger.warning(f"Could not send group view to: {uuid}.")

        self._broadcast_handler.send({"intention": str(Intention.MONITOR_MESSAGE), "group_view": self._group_view})

    def _on_received_grp_view(self, data):
        group_view = {}
        for key, value in data["group_view"].items():
            group_view[key] = tuple(value)
        for new_member in set(group_view.keys()) - set(self._group_view.keys()):
            self._rom_handler.register_new_member(new_member)
        self._group_view = group_view
        self._rom_handler.set_group_view(self._group_view)
        self._logger.debug(
            f"Received updated group view with {len(list(self._group_view.keys()))} items."
        )

    def _on_accepted(self, data):
        self._logger.info("Found a group leader.")
        self._state = State.MEMBER
        self._entries = data["entries"]
        self._current_leader = data.get("leader")
        self._group_view = data.get("group_view")
        self._logger.debug(
            f"I have been accepted by leader {self._current_leader}. Group view has been populated."
        )
        self._set_leader(False)
        self._rom_handler.sync_state(
            json.loads(data.get("rnumbers")),
            json.loads(data.get("deliver_queue")),
        )

    def _request_join(self, rejoin=False):
        self._tcp_handler._paused = True
        mes = {
            "intention": str(Intention.IDENT_SERVER),
            "uuid": f"{self._uuid}",
            "address": self._my_ip,
            "port": self._tcp_handler.port
        }

        self._broadcast_handler.send(mes)
        self._logger.info("Looking for a server group.")

        if not rejoin:
            tries = 0
            while tries < MAX_ENTRIES:
                data, _ = self._tcp_handler.listen()
                if data is not None:
                    if data.get("intention") == str(Intention.ACCEPT_SERVER):
                        self._on_accepted(data)
                        break

                    if data.get("intention") == str(Intention.TRY_AGAIN):
                        self._broadcast_handler.send(mes)
                else:
                    tries += 1

            self._tcp_handler._paused = False
            if self._state == State.PENDING:
                self._logger.info(
                    "Could not find a leader. Declaring myself."
                )
                self._set_leader(True)
                self._group_view[self._uuid] = (
                    self._my_ip,
                    self._tcp_handler.port,
                )
                self._rom_handler.set_group_view(self._group_view)
        else:
            self._tcp_handler._paused = False

        self._promote_monitoring_data()

    def _register_server(self, data, batch=False):
        self._group_view[data["uuid"]] = (data["address"], data["port"])

        welcome_msg = {
            "intention": str(Intention.ACCEPT_SERVER),
            "leader": f"{self._uuid}",
            "group_view": self._group_view,
            "rnumbers": json.dumps(self._rom_handler._rnumbers),
            "deliver_queue": json.dumps(self._rom_handler._deliver_queue),
            "entries": self._entries,
        }

        self._rom_handler.register_new_member(data["uuid"])
        if not self._tcp_handler.send(welcome_msg, self._group_view[data["uuid"]]):
            #TODO handle this case?
            self._logger.warn("Added a server to my groupview but was unable to send it a welcome message!")
        self._logger.info(
            "Received server join request from {}".format(
                (data["address"], data["port"])
            )
        )

        self._heartbeats[data["uuid"]] = {"ts": datetime.datetime.now().timestamp(), "strikes": 0}

        if not batch:
            self._logger.debug("New group view is: {}".format(self._group_view))
            self._distribute_group_view()

            self._logger.debug("Checking election required.")
            if self._election_required():
                self._logger.info("Election is required, starting election.")
                self._start_election()
            else:
                self._logger.debug("No election required.")
                if self._can_byzantine():
                    self._rom_handler.pause()
                    self._start_byzantine()

    # election methods --------------------------------------------------------

    def _start_election(self):
        election_msg = {
            "intention": str(Intention.ELECTION_MESSAGE),
            "mid": self._uuid,
            "is_leader": False,
        }
        self._logger.info(f"Starting election.")
        self._participating = True
        self._promote_monitoring_data()
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

        neighbor = self._get_neighbor()
        self._logger.info(f"Sending election message to {neighbor}.")
        if neighbor == self._uuid:
            self._logger.warning(
                "Could not find any available neighbors. Calling my own method."
            )
            self._on_election_message(message)

        else:
            tries = 0
            success = False
            while tries <= 3:
                success = self._tcp_handler.send(message, self._group_view[neighbor])
                if success:
                    break
                self._logger.warning("Retrying..")
                time.sleep(0.5)
                tries += 1

            if not success:
                self._logger.warning(f"Could not send election message to {neighbor}. Will start a new election.")

                self._group_view.pop(neighbor)

                self._start_election()

    def _on_election_message(self, data):
        self._logger.debug(f"Received an Election Message from {data['mid']}")
        neighbor = self._get_neighbor()

        if data["is_leader"]:
            self._logger.debug(f"Message is a leader message.")
            self._logger.info(f"Setting {data['mid']} to leader.")

            if self._participating:
                self._current_leader = data["mid"]
                self._participating = False
                if self._state == State.LEADER:
                    self._set_leader(False)
                self._state = State.MEMBER
                self._logger.debug(f"Relaying leader message to {neighbor}.")
                self._send_election_message(data)
            else:
                if self._uuid != data["mid"]:
                    self._logger.warning("Received a leader message which is not my own even though I am not participating.")
                    self._start_election()
                else:
                    self._set_leader(True)

                    self._logger.debug(
                        "Received my own leader message, will terminate the election."
                    )

                    self._logger.info("Updating group view.")
                    group_view = deepcopy(self._group_view)

                    for uuid, address in self._group_view.items():
                        if not self._tcp_handler.send({"intention": str(Intention.PING)}, address):
                            group_view.pop(uuid)

                    self._group_view = group_view

                    self._distribute_group_view()
                    if self._can_byzantine():
                        self._rom_handler.pause()
                        self._start_byzantine()
            self._promote_monitoring_data()

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
            self._logger.debug(f"Received my own election message.")
            self._logger.info("Declaring myself leader.")
            self._logger.debug(f"Sending leader message to {neighbor}")
            self._current_leader = self._uuid
            data["mid"] = self._uuid
            data["is_leader"] = True
            self._participating = False
            self._send_election_message(data)

        else:
            self._logger.warning("Looks like a new election. Todo: handle this")

    # byzantine ---------------------------------------------------------------

    def _can_byzantine(self):
        n = len(self._group_view)
        f = math.floor((n - 1) / 3)
        return f > 0

    def _start_byzantine(self, id = None):
        if id != None:
            if self._byzantine_history[id] == ByzantineStates.ABORTED:
                return

            self._byzantine_history[id] = ByzantineStates.ABORTED

        id = str(uuid4())
        self._byzantine_leader_cache = ByzantineLeaderCache(id)
        self._byzantine_history[self._byzantine_leader_cache.id] = ByzantineStates.STARTED
        self._promote_monitoring_data()

        v = self._entries
        n = len(self._group_view)
        f = math.floor((n - 1) / 3)
        if f == 0:
            return

        self._logger.info("Starting byzantine algorithm")
        dests = list(set(self._group_view.keys()) - set([self._uuid]))
        om = {
            "intention": str(Intention.OM),
            "v": v,
            "dests": dests,
            "list": [self._uuid],
            "faulty": f,
            "id": self._byzantine_leader_cache.id,
        }
        for uuid in dests:
            if not self._tcp_handler.send(om, self._group_view[uuid]):
                self._logger.warning(f"Could not send om to: {uuid}.")

    def _stop_byzantine(self, om):
        if self._byzantine_leader_cache == None:
            self._logger.error(f"We shouldn't get byzantine messages. Byzantine isn't running: {om}")
            return

        self._byzantine_leader_cache.results.append(om["from"])
        self._byzantine_leader_cache.counter[om["result"]] += 1
        leader_less_group = set(self._group_view.keys()) - set([self._uuid])
        missing = leader_less_group - set(self._byzantine_leader_cache.results)
        if len(missing) == 0:
            self._logger.info(f"Stopping byzantine algorithm")
            mc = self._byzantine_leader_cache.counter.most_common()
            self._logger.info("Resuming ROM")
            self._byzantine_leader_cache = None
            self._byzantine_history[om["id"]] = ByzantineStates.FINISHED
            self._entries = mc[0][0]
            self._rom_handler.resume(value=mc[0][0])
            self._promote_monitoring_data()

    def _on_byzantine_om(self, om):
        self._logger.debug(f"Received byzantine message: {om}")
        byzantine_id = om["id"]
        if self._byzantine_member_cache == None:
            self._logger.info("Started byzantine")
            self._byzantine_member_cache = ByzantineMemberCache(byzantine_id, len(self._group_view))
            self._byzantine_history[byzantine_id] = ByzantineStates.STARTED
            self._promote_monitoring_data()
        else:
            if byzantine_id not in self._byzantine_history and self._byzantine_member_cache.id != byzantine_id:
                self._logger.info("Aborted and restarted byzantine")
                self._byzantine_history[self._byzantine_member_cache.id] = ByzantineStates.ABORTED
                self._byzantine_member_cache = ByzantineMemberCache(byzantine_id, len(self._group_view))
                self._byzantine_history[byzantine_id] = ByzantineStates.STARTED

        if not self._byzantine_member_cache.tree.is_full():
            dests = list(set(om["dests"]) - set([self._uuid]))
            l = om["list"]
            f = om["faulty"]
            self._byzantine_member_cache.tree.push(deepcopy(l), om["v"])
            if f - 1 >= 0:
                l.insert(0, self._uuid)
                om_new = {
                    "intention": str(Intention.OM),
                    "v": self._entries,
                    "dests": dests,
                    "list": l,
                    "faulty": f - 1,
                    "id": byzantine_id,
                }
                for uuid in dests:
                    if not self._tcp_handler.send(om_new, self._group_view[uuid]):
                        self._logger.warning(f"Could not send om to: {uuid}. Requesting byzantine restart")
                        if self._current_leader != self._uuid:
                            request = {
                                "intention": str(Intention.OM_RESTART),
                                "id": byzantine_id,
                            }
                            self._tcp_handler.send(request, self._group_view[self._current_leader])
                        else:
                            self._start_byzantine(byzantine_id)

        # Are we now done? Then complete the algorithm
        if self._byzantine_member_cache.tree.is_full():
            res = self._byzantine_member_cache.tree.complete()
            self._byzantine_member_cache = None
            self._byzantine_history[byzantine_id] = ByzantineStates.FINISHED
            self._promote_monitoring_data()
            om_new = {
                "intention": str(Intention.OM),
                "from": self._uuid,
                "result": res,
                "id": byzantine_id,
            }
            if not self._tcp_handler.send(om_new, self._group_view[self._current_leader]):
                self._logger.warning(f"Could not send stop om to current leader")

    # heartbeat methods -------------------------------------------------------

    def _send_heartbeat(self):
        if not self._participating:
            msg = {"intention": str(Intention.HEARTBEAT), "uuid": f"{self._uuid}", "address": self._my_ip, "port": self._tcp_handler.port }
            if not self._tcp_handler.send(msg, self._group_view[self._current_leader]):
                self._logger.warning("Leader seems to be offline, starting new election.")
                self._start_election()
        else:
            self._logger.debug("Not sending heartbeat because I am participating in an election.")

        self._promote_monitoring_data()

    def _check_heartbeats(self):

        self._promote_monitoring_data()

        if self._participating:
            self._logger.debug("Participating in an election. Not checking heartbeats.")

        else:
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
                            self._logger.info(f"Node {uuid} has timed out twice in a row. Removing.")
                            remove.append(uuid)
                else:
                    self._logger.info(
                        f"Node {uuid} does not appear to be in group view. Removing."
                    )
                    remove.append(uuid)

            if remove:
                for uid in remove:
                    if uid in self._group_view:
                        self._group_view.pop(uid)
                    if uid in self._heartbeats:
                        self._heartbeats.pop(uid)
                self._distribute_group_view()

            if len(self._group_view) == 1:
                self._logger.info("Looks like I am the only server.")
                self._request_join(rejoin=True)

    def _on_received_heartbeat(self, data):
        if self._state == State.LEADER:
            if data['uuid'] in self._group_view:
                self._logger.debug(f"Received heartbeat from {data['uuid']}.")
                self._heartbeats[data["uuid"]] = {"ts": datetime.datetime.now().timestamp(), "strikes": 0}
            else:
                self._logger.warning(
                    f"Received heartbeat from {data['uuid']} who is not in group view. Will register them as a new member."
                )
                self._register_server(data)
        else:
            self._tcp_handler.send({"intention": str(Intention.NOT_LEADER)}, (data['address'],data['port']))

    def _on_heartbeat_timeout(self, heartbeat_func):
        self._logger.debug(f"Heartbeat timed out, calling {heartbeat_func}.")
        heartbeat_func()

    # client methods ----------------------------------------------------------

    def _register_client(self, data):
        mes = {
            "intention": str(Intention.ACCEPT_CLIENT),
            "uuid": self._uuid,
            "address": self._my_ip,
            "port": self._tcp_handler.port,
            "entries": self._entries
        }
        self._logger.info(f"Trying to register a client with uuid {data['uuid']}")
        if self._tcp_handler.send(mes, (data['address'],data['port'])):
            pass
        else:
            self._logger.warn("Failed to accept a client, seems to have already disappeared again!")

    def _update_client_entries(self):
        to_remove = []
        for (uuid,addr_and_port) in self._clients.items():
            if not self._tcp_handler.send({"intention": str(Intention.UPDATE_ENTRIES), "entries": self._entries}, addr_and_port):
                to_remove.append(uuid)
                self._logger.warn("Marking a client for removal due to failure of sending them a message")
        for uuid in to_remove:
            self._clients.pop(uuid)

    def _on_request_action(self,res):
        if not self._clients.get(res["uuid"]):
            self._clients[res["uuid"]] = (res["address"],res["port"])
            self._logger.info("Seems like a discarded client reconnected, readding it to the client list.")
        self._logger.info(f"Client {res['uuid']} is requesting an action.")
        self._requests.put(res)
        self._update_lock()

    def _update_lock(self, data={"intention": "TODO"}): #TODO
        if self._lock == LockState.CLOSED:
            if data["intention"] == str(Intention.UNLOCK):
                self._lock = LockState.OPEN
                self._logger.info("Lock unlocked by someone else!")
        if self._lock == LockState.OPEN:
            if data["intention"] == str(Intention.LOCK):
                if data["uuid"] == self._uuid:
                    self._lock = LockState.MINE
                    self._logger.info("Lock acquired!")
                    while not self._requests.empty():
                        res = self._requests.get()
                        if res["increase"]:
                            if self._entries < MAX_ENTRIES:
                                mes = {
                                    "intention": str(Intention.ACCEPT_ENTRY),
                                    "uuid": self._uuid
                                    }
                                if self._tcp_handler.send(mes, (res["address"],res["port"])):
                                    self._entries += 1
                                    self._logger.info("Granted someone entry. Current count: " + str(self._entries) + " of " + str(MAX_ENTRIES))
                                else:
                                    self._logger.warn("Failed to send entry acceptance to a client, ignoring the request!")
                            else:
                                mes = {
                                    "intention": str(Intention.DENY_ENTRY),
                                    "uuid": self._uuid
                                    }
                                self._tcp_handler.send(mes, (res["address"],res["port"]))
                        else:
                            self._entries -= 1
                            self._logger.info("Someone left the venue. Current count: " + str(self._entries) + " of " + str(MAX_ENTRIES))
                    self._update_client_entries()
                    self._rom_handler.send({"uuid": self._uuid, "intention": str(Intention.UPDATE_ENTRIES), "entries": self._entries})
                    self._rom_handler.send({"uuid": self._uuid, "intention": str(Intention.UNLOCK)})
                else:
                    self._lock = LockState.CLOSED
                    self._logger.info("Lock acquired by someone else!")
            elif not self._requests.empty():
                self._rom_handler.send({"intention":str(Intention.LOCK), "uuid": self._uuid})
        if self._lock == LockState.MINE:
            if data["intention"] == str(Intention.UNLOCK) and data["uuid"] == self._uuid:
                self._lock = LockState.OPEN
                self._logger.info("Lock unlocked by me!")


    # other methods -----------------------------------------------------------

    def _promote_monitoring_data(self):
        msg = {
            "intention": str(Intention.MONITOR_MESSAGE),
            "hostname": self._my_hostname,
            "ip": self._my_ip,
            "port":self._tcp_handler.port,
            "uuid": self._uuid,
            "clients": self._clients,
            "election": self._participating,
            "byzantine": self._byzantine_leader_cache is not None or self._byzantine_member_cache is not None,
            "state": self._state.name,
            "entries": self._entries
        }
        self._broadcast_handler.send(msg)

    def _set_leader(self, state=True):
        if state:
            self._state = State.LEADER
            if self._heartbeat_timer is not None:
                self._heartbeat_timer.cancel()
            self._heartbeat_timer = RepeatTimer(
                HEARTBEAT_TIMEOUT + 5, self.QUEUE.put, args=[Invokeable(ON_HEARTBEAT_TIMEOUT, heartbeat_func=self._check_heartbeats)]
            )
            self._heartbeat_timer.start()
        else:
            if self._heartbeat_timer is not None:
                self._heartbeat_timer.cancel()
            self._heartbeat_timer = RepeatTimer(HEARTBEAT_TIMEOUT, self.QUEUE.put, args=[Invokeable(ON_HEARTBEAT_TIMEOUT, heartbeat_func=self._send_heartbeat)]
            )
            self._heartbeat_timer.start()

    # process methods ---------------------------------------------------------

    def _shut_down(self):
        self._logger.info("Shutting down.")
        leader_address = self._group_view.get(self._current_leader)

        self._broadcast_handler.send({"intention": str(Intention.MONITOR_MESSAGE), "uuid": self._uuid, "leaving": True})

        msg = {"intention": str(Intention.SHUTDOWN_SERVER), "uuid": f"{self._uuid}"}

        self._logger.debug("Shutting down connection handlers.")
        self._tcp_handler.join()
        self._broadcast_handler.join()
        #TODO currently doesn't work
        self._rom_handler.join()
        self._logger.debug("Stopping heartbeat timer.")
        if self._heartbeat_timer is not None:
            self._heartbeat_timer.cancel()

        if leader_address and self._current_leader != self._uuid:
            self._logger.debug("Sending shutdown signal to leader.")
            self._tcp_handler.send(msg, leader_address)
        else:
            self._logger.debug("Broadcasting shutdown signal.")
            self._broadcast_handler.send(msg)

    def run(self):

        self._logger.info("Starting Server...")

        self._request_join()

        self._logger.info("Starting TCP hander.")
        self._tcp_handler.start()
        self._logger.info("Starting Broadcast hander.")
        self._broadcast_handler.start()
        self._logger.info("Starting Multicast hander.")
        self._rom_handler.start()

        self._logger.info("Running.")
        try:
            while True:
                try:
                    try:
                        item = self.QUEUE.get(block=False)
                        if item.signal == ON_TCP_MESSAGE:
                            self._on_tcp_msg(**item.kwargs)
                        elif item.signal == ON_BROADCAST_MESSAGE:
                            self._on_udp_msg(**item.kwargs)
                        elif item.signal == ON_MULTICAST_MESSAGE:
                            self._on_rom_msg(**item.kwargs)
                        elif item.signal == ON_HEARTBEAT_TIMEOUT:
                            self._on_heartbeat_timeout(**item.kwargs)

                    except queue.Empty:
                        pass
                except Exception as e:
                    self._logger.error(e)
        except KeyboardInterrupt:
            self._logger.info("Shutting down...")
            self._shut_down()
            self._logger.info("Shut down successfull.")
            try:
                sys.exit(0)
            except SystemExit:
                os._exit(0)
