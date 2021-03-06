import os
import queue
import signal
import sys
import threading

from PySide2 import QtCore, QtGui, QtWidgets
from src.utils.tcp_handler import TCPHandler

from ..utils.broadcast_handler import BroadcastHandler
from ..utils.constants import Intention
from ..utils.signals import ON_BROADCAST_MESSAGE

os.environ['QT_MAC_WANTS_LAYER'] = '1'

class UPDThread(QtCore.QThread):

    udp_message = QtCore.Signal(object)

    def __init__(self, queue, parent=None):
        super().__init__(parent)
        self._queue = queue
        self._stopped = False

    def run(self):
        while not self._stopped:
            try:
                item = self._queue.get(block=False)
                if item.signal == ON_BROADCAST_MESSAGE:
                    self.udp_message.emit(item.kwargs["data"])

            except queue.Empty:
                pass

    def stop(self):
        self._stopped = True
        return self.wait()
class Monitor(QtWidgets.QDialog):

    QUEUE = queue.SimpleQueue()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._broadcast_handler = BroadcastHandler(self.QUEUE)

        self._thread = UPDThread(self.QUEUE, self)
        self._thread.start()

        self._tcp_handler = TCPHandler(queue.SimpleQueue())
        self._tcp_handler.start()

        self._thread.udp_message.connect(self._on_udp_msg)

        self._allow_signal = True

        lyt = QtWidgets.QVBoxLayout(self)

        self._model = QtGui.QStandardItemModel()
        self._model.dataChanged.connect(self._on_data_changed)

        self._model.setHorizontalHeaderLabels(["Server", "Name", "Clients", "Entries", "Participating", "Byzantine", "State"])

        self._view = QtWidgets.QTableView()
        self._view.setModel(self._model)
        self._view.setColumnHidden(0, True)
        self._view.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.Stretch)
        self._view.horizontalHeader().setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeToContents)
        self._view.horizontalHeader().setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeToContents)
        self._view.verticalHeader().setSectionResizeMode(QtWidgets.QHeaderView.ResizeToContents)
        lyt.addWidget(self._view)

        hbox = QtWidgets.QHBoxLayout()
        lyt.addLayout(hbox)
        hbox.addStretch()

        self._byz_btn = QtWidgets.QPushButton("Run Byzantine")
        hbox.addWidget(self._byz_btn)

        self._byz_btn.clicked.connect(self._run_byz)
        self._broadcast_handler.start()

    def _run_byz(self):
        self._broadcast_handler.send({"intention": str(Intention.RUN_BYZ)})

    def _on_udp_msg(self, data=None, addr=None):
        if data["intention"] == str(Intention.MONITOR_MESSAGE):
            if data.get("group_view") is not None:
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
                self._allow_signal = False
                self._update_server(data)

            else:
                self._allow_signal = False
                self._add_server(data)

            self._allow_signal = True

    def _on_data_changed(self, tl, br, roles):
        if self._allow_signal:
            value = tl.data()
            index = self._model.index(tl.row(), 0)
            address = index.data(QtCore.Qt.UserRole+3)

            print(f"setting entries on {address} to {value}")

            print(self._tcp_handler.send({"intention": str(Intention.MANUAL_VALUE_OVERRIDE), "value": value}, address))

    def _remove_server(self, uuid):
        for item in self._model.findItems(uuid):
            row = self._model.indexFromItem(item).row()
            self._model.removeRow(row)

    def _add_server(self, server):
        item = QtGui.QStandardItem(server["uuid"])
        item.setData((server.get("ip"), server.get("port")), QtCore.Qt.UserRole+3)
        name_item = QtGui.QStandardItem(self._get_name(server))
        clients_item = QtGui.QStandardItem('\n'.join([i for i in server.get('clients', [])]))
        entries_item = QtGui.QStandardItem(f'{server.get("entries")}')
        election_item = QtGui.QStandardItem(f'{server.get("election")}')
        state_item = QtGui.QStandardItem(f'{server.get("state")}')
        byzantine_item = QtGui.QStandardItem(f'{server.get("byzantine")}')

        row = [
            item,
            name_item,
            clients_item,
            entries_item,
            election_item,
            byzantine_item,
            state_item,
        ]

        self._model.appendRow(row)

    def _get_name(self, data):
        return f"{data.get('hostname')} | {data.get('ip')}:{data.get('port')}"

    def _update_server(self, server):
        for item in self._model.findItems(server["uuid"]):
            index = self._model.indexFromItem(item)
            row = index.row()

            name_index = self._model.index(row, 1)
            self._model.setData(name_index, self._get_name(server))

            clients_index = self._model.index(row, 2)
            self._model.setData(clients_index, '\n'.join([i for i in server.get('clients', [])]))

            entries_index = self._model.index(row, 3)
            self._model.setData(entries_index, f'{server.get("entries")}')

            election_index = self._model.index(row, 4)
            self._model.setData(election_index, f'{server.get("election")}')

            byzantine_index = self._model.index(row, 5)
            self._model.setData(byzantine_index, f'{server.get("byzantine")}')

            state_index = self._model.index(row, 6)
            self._model.setData(state_index, f'{server.get("state")}')

    def closeEvent(self, event):
        self._thread.stop()
        super().closeEvent(event)

def start_monitor():
    app = QtWidgets.QApplication().instance()
    signal.signal(signal.SIGINT, signal.SIG_DFL)

    monitor = Monitor()
    monitor.show()

    sys.exit(app.exec_())
