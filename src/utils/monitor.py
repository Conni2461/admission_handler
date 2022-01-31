import signal
import sys

from louie import dispatcher
from PySide6 import QtCore, QtGui, QtWidgets

from ..utils.broadcast_handler import BroadcastHandler
from ..utils.constants import MONITOR_MESSAGE
from ..utils.signals import ON_BROADCAST_MESSAGE


class Monitor(QtWidgets.QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._broadcast_handler = BroadcastHandler()

        dispatcher.connect(
                self._on_udp_msg, signal=ON_BROADCAST_MESSAGE, sender=self._broadcast_handler
            )

        lyt = QtWidgets.QVBoxLayout(self)

        self._model = QtGui.QStandardItemModel()

        self._model.setHorizontalHeaderLabels(["Server", "Clients", "Entries", "Participating", "State"])

        self._view = QtWidgets.QTableView()
        self._view.setModel(self._model)
        self._view.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.Stretch)
        self._view.horizontalHeader().setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeToContents)
        self._view.horizontalHeader().setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeToContents)
        lyt.addWidget(self._view)

        self._broadcast_handler.start()

    def _on_udp_msg(self, data=None, addr=None):
        if data["intention"] == MONITOR_MESSAGE:
            if data.get("group_view"):
                for key in data["group_view"]:
                    if not self._model.findItems(key):
                        self._add_server({"uuid": key})

                for i in range(self._model.rowCount()):
                    uuid = self._model.index(i, 0).data()
                    if uuid not in data["group_view"]:
                        self._model.removeRow(i)

            elif data.get("leaving"):
                self._remove_server(data["uuid"])

            elif self._model.findItems(data["uuid"]):
                self._update_server(data)

            else:
                self._add_server(data)

    def _remove_server(self, uuid):
        for item in self._model.findItems(uuid):
            row = self._model.indexFromItem(item).row()
            self._model.removeRow(row)

    def _add_server(self, server):
        item = QtGui.QStandardItem(server["uuid"])
        clients_item = QtGui.QStandardItem(f"{','.join([i for i in server.get('clients', [])])}")
        entries_item = QtGui.QStandardItem(f'{server.get("entries")}')
        election_item = QtGui.QStandardItem(f'{server.get("election")}')
        state_item = QtGui.QStandardItem(f'{server.get("state")}')

        cnt = self._model.rowCount()
        self._model.setItem(cnt, 0, item)
        self._model.setItem(cnt, 1, clients_item)
        self._model.setItem(cnt, 2, entries_item)
        self._model.setItem(cnt, 3, election_item)
        self._model.setItem(cnt, 4, state_item)

    def _update_server(self, server):
        for item in self._model.findItems(server["uuid"]):
            index = self._model.indexFromItem(item)
            row = index.row()

            clients_index = self._model.index(row, 1)
            self._model.setData(clients_index, f"{','.join([i for i in server.get('clients', [])])}")

            entries_index = self._model.index(row, 2)
            self._model.setData(entries_index, f'{server.get("entries")}')

            election_index = self._model.index(row, 3)
            self._model.setData(election_index, f'{server.get("election")}')

            state_index = self._model.index(row, 4)
            self._model.setData(state_index, f'{server.get("state")}')

def start_monitor():
    app = QtWidgets.QApplication().instance()
    signal.signal(signal.SIGINT, signal.SIG_DFL)

    monitor = Monitor()
    monitor.show()

    sys.exit(app.exec_())
