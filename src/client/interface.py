import os
import queue
import signal
import sys
import threading
from typing import Optional

from louie import dispatcher
from PySide2 import QtCore, QtWidgets

from ..utils.common import Invokeable
from ..utils.constants import MAX_ENTRIES
from ..utils.signals import ON_ENTRY_REQUEST
from .signals import (ON_ACCESS_RESPONSE, ON_CLIENT_SHUTDOWN, ON_COUNT_CHANGED,
                      ON_REQUEST_ACCESS, ON_SERVER_CHANGED)

os.environ['QT_MAC_WANTS_LAYER'] = '1'

class ClientListener(QtCore.QThread):

    count_changed = QtCore.Signal(object)
    request_access = QtCore.Signal(object)
    access_response = QtCore.Signal(object)
    server_changed = QtCore.Signal(object)
    client_shutdown = QtCore.Signal(object)

    def __init__(self, queue, parent=None):
        super().__init__(parent)
        self._queue = queue
        self._stopped = False

    def run(self):
        while not self._stopped:
            try:
                item = self._queue.get(block=False)
                if item.signal == ON_COUNT_CHANGED:
                    self.count_changed.emit(item.kwargs)
                if item.signal == ON_REQUEST_ACCESS:
                    self.request_access.emit(item.kwargs)
                if item.signal == ON_ACCESS_RESPONSE:
                    self.access_response.emit(item.kwargs)
                if item.signal == ON_SERVER_CHANGED:
                    self.server_changed.emit(item.kwargs)
                if item.signal == ON_CLIENT_SHUTDOWN:
                    self.client_shutdown.emit(item.kwargs)

            except queue.Empty:
                pass

    def stop(self):
        self._stopped = True
        return self.wait()

class ClientUI(QtWidgets.QDialog):
    def __init__(self, client, parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)

        self._client = client
        self._client_listener = ClientListener(client.UI_QUEUE, self)

        self._count = 0

        self._client_listener.count_changed.connect(self._on_count_changed)
        self._client_listener.request_access.connect(self._on_request_access)
        self._client_listener.access_response.connect(self._on_access_response)
        self._client_listener.server_changed.connect(self._on_server_changed)
        self._client_listener.client_shutdown.connect(self._on_client_shutdown)

        self._setup_ui()

        self._client_listener.start()


    def _setup_ui(self):
        lyt = QtWidgets.QVBoxLayout(self)

        self._server_lbl = QtWidgets.QLabel("Not connected to a server.")
        lyt.addWidget(self._server_lbl)

        self._count_lbl = QtWidgets.QLabel(f"Current count: 0/{MAX_ENTRIES}")
        lyt.addWidget(self._count_lbl)

        self._action_btn = QtWidgets.QPushButton("Request Access")
        lyt.addWidget(self._action_btn)

        self._leaving_btn = QtWidgets.QPushButton("Someone Leaving")
        lyt.addWidget(self._leaving_btn)

        self._status_lbl = QtWidgets.QLabel()
        lyt.addWidget(self._status_lbl)

        self._action_btn.clicked.connect(self._on_action_btn_clicked)
        self._leaving_btn.clicked.connect(self._on_leaving_btn_clicked)


    def _on_leaving_btn_clicked(self):
        self._client.QUEUE.put(Invokeable(ON_ENTRY_REQUEST, inc=False))

    def _on_action_btn_clicked(self):
        self._client.QUEUE.put(Invokeable(ON_ENTRY_REQUEST))

    def _on_count_changed(self, data):
        if data['count'] < self._count:
            self._status_lbl.setText("Someone has left the venue.")

        self._count = int(data['count'])
        self._count_lbl.setText(f"Current count: {data['count']}/{MAX_ENTRIES}.")

    def _on_request_access(self, *args):
        self._action_btn.setEnabled(False)
        self._action_btn.setText("Requesting Access..")

    def _on_access_response(self, data):
        response = data["response"]
        if response["status"]:
            self._action_btn.setText("Access Granted!")
            if response.get("message"):
                self._status_lbl.setText(f"Last action: {response['message']}")
        else:
            if response.get("message"):
                self._status_lbl.setText(f"Last action: {response['message']}.")

        self._action_btn.setText("Request Access")
        self._action_btn.setEnabled(True)

    def _on_server_changed(self, data):
        server = data["server"]
        count = data["count"]
        msg = f"Currently connected to server: :{server}."
        self._server_lbl.setText(msg)
        self._count_lbl.setText(f"Current count: {count}/{MAX_ENTRIES}.")

    def _on_client_shutdown(self, *args):
        self.close()

    def closeEvent(self, event):
        self._client_listener.stop()
        super().closeEvent(event)

def launch(client):
    app = QtWidgets.QApplication(sys.argv)
    signal.signal(signal.SIGINT, signal.SIG_DFL)

    client_thread = threading.Thread(target=client.run)
    client_thread.start()

    ui = ClientUI(client)
    ui.show()

    ret = app.exec_()
    client_thread.join()
    sys.exit(ret)
