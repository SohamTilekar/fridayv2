# global_shares.py
# This file is use to share py objects accross files without circular import
from flask_socketio import SocketIO
from google import genai
from typing import Any, TypedDict, Callable, TYPE_CHECKING

if TYPE_CHECKING:
    from main import ChatHistory, Content, File, FunctionCall, FunctionResponce


class Shared(TypedDict):
    socketio: SocketIO
    mail_service: Any
    client: genai.Client
    take_permision: Callable[[str], bool]
    chat_history: "ChatHistory"
    file: type["File"]
    content: type["Content"]
    function_call: type["FunctionCall"]
    function_responce: type["FunctionResponce"]


global_shares: Shared = {
    "socketio": None,
    "mail_service": None,
    "client": None,
    "take_permision": lambda x: False,
    "chat_history": None,
    "file": None,
    "content": None,
    "function_call": None,
    "function_responce": None
}  # type: ignore
