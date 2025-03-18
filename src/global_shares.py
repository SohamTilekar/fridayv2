from flask_socketio import SocketIO
from typing import Any, Optional, TypedDict, Callable

class Shared(TypedDict):
    socketio: Optional[SocketIO]
    mail_service: Optional[Any]
    take_permision: Callable[[str], bool]

global_shares: Shared = {"socketio": None,"mail_service": None,"take_permision": lambda x: False}