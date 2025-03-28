from flask_socketio import SocketIO
from google import genai
from typing import Any, Optional, TypedDict, Callable

class Shared(TypedDict):
    socketio: Optional[SocketIO]
    mail_service: Optional[Any]
    client: Optional[genai.Client]
    take_permision: Callable[[str], bool]

global_shares: Shared = {"socketio": None,"mail_service": None, "client": None,"take_permision": lambda x: False}
