from flask_socketio import SocketIO
from typing import Any, TypedDict

class Shared(TypedDict):
    socketio: SocketIO
    mail_service: Any

global_shares: Shared = {"socketio": None, "mail_service": None}