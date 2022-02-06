import os
import signal
import sys
import threading
import time
from typing import Optional

from louie import dispatcher
from PySide2 import QtWidgets

from ..utils.constants import MAX_ENTRIES
from ..utils.signals import ON_ENTRY_REQUEST
from .signals import (ON_ACCESS_RESPONSE, ON_CLIENT_SHUTDOWN, ON_COUNT_CHANGED,
                      ON_REQUEST_ACCESS, ON_SERVER_CHANGED)

os.environ['QT_MAC_WANTS_LAYER'] = '1'
class ClientUI(QtWidgets.QDialog):
    def __init__(self, parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)

        self._client = None

        self._setup_ui()


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

    def set_client(self, client):

        self._client = client

        dispatcher.connect(self._on_count_changed, signal=ON_COUNT_CHANGED, sender=client)
        dispatcher.connect(self._on_request_access, signal=ON_REQUEST_ACCESS, sender=client)
        dispatcher.connect(self._on_access_response, signal=ON_ACCESS_RESPONSE, sender=client)
        dispatcher.connect(self._on_server_changed, signal=ON_SERVER_CHANGED, sender=client)
        dispatcher.connect(self._on_client_shutdown, signal=ON_CLIENT_SHUTDOWN, sender=client)

    def _on_leaving_btn_clicked(self):
        dispatcher.send(signal=ON_ENTRY_REQUEST,sender=self._client.number,
                        inc=False
                    )

    def _on_action_btn_clicked(self):
        dispatcher.send(signal=ON_ENTRY_REQUEST,sender=self._client.number)

    def _on_count_changed(self, count):
        self._count_lbl.setText(f"Current count: {count}/{MAX_ENTRIES}.")

    def _on_request_access(self):
        self._action_btn.setEnabled(False)
        self._action_btn.setText("Requesting Access..")

    def _on_access_response(self, response):
        if response["status"]:
            self._action_btn.setText("Access Granted!")
            if response.get("message"):
                self._status_lbl.setText(f"Last action: {response['message']}")
            # self._status_lbl.setStyleSheet("color: ForestGreen;")
        else:
            self._action_btn.setText("Access Denied!")
            if response.get("message"):
                self._status_lbl.setText(f"Last action: {response['message']}.")
            # self._status_lbl.setStyleSheet("color: Crimson;")

        self._action_btn.setText("Request Access")
        self._action_btn.setEnabled(True)

    def _on_server_changed(self, server, count):
        msg = f"Currently connected to server: :{server}."
        self._server_lbl.setText(msg)
        self._count_lbl.setText(f"Current count: {count}/{MAX_ENTRIES}.")

    def _on_client_shutdown(self):
        self.close()

def launch(client):
    app = QtWidgets.QApplication(sys.argv)
    signal.signal(signal.SIGINT, signal.SIG_DFL)

    client_thread = threading.Thread(target=client.run)
    client_thread.start()

    ui = ClientUI()
    ui.set_client(client)
    ui.show()

    ret = app.exec_()
    sys.exit(ret)