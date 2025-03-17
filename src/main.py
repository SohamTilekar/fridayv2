# main.py
import re
from rich import print
from flask import Flask, render_template, redirect, url_for
from flask_socketio import SocketIO
from google import genai
from google.genai import types
import prompt
import config
import uuid
from io import BytesIO  # Import BytesIO
from typing import Any, Literal, Optional, Iterator
from mail import start_checking_mail
from global_shares import global_shares
import notification
import json
import os
import base64
import time
import datetime
import utils
import threading
import tools

app = Flask("Friday")
socketio = SocketIO(app)
global_shares["socketio"] = socketio

client = genai.Client(api_key=config.GOOGLE_API)

model: Optional[str] = None # None for Auto
selected_tools: Optional[list[tools.ToolLiteral]] = None # None for Auto

#region

class File:
    type: str  # mime types = ""
    content: bytes | str = b""
    filename: str = ""
    # whether the current attachment is the summary
    is_summary: bool = False
    id: str = ""
    cloud_uri: Optional[types.File] = None  # URI of the file in the cloud

    def __init__(self, content: bytes | str, type: str, filename: str, cloud_uri: Optional[types.File] = None, id: Optional[str] = None, is_summary: bool = False):
        self.content = content
        self.type = type
        self.filename = filename
        self.id = str(uuid.uuid4()) if id is None else id
        self.cloud_uri = cloud_uri
        self.is_summary = is_summary

    def delete(self):
        if self.cloud_uri and self.is_expiration_valid(self.cloud_uri.expiration_time):
            client.files.delete(name=self.cloud_uri.name)  # type: ignore

    @staticmethod
    def _generate_valid_video_file_id():
        """Generates a valid ID that conforms to the naming requirements."""
        base_id = str(uuid.uuid4()).lower()[:35]
        valid_id = re.sub(r'^[^a-z0-9]+|[^a-z0-9]+$', '', base_id)
        return valid_id

    @staticmethod
    def is_expiration_valid(expiration_time: datetime.datetime | None) -> bool:
        if expiration_time is None:
            return True
        now = datetime.datetime.now(datetime.timezone.utc)
        ten_minutes_from_now = now + datetime.timedelta(minutes=10)

        return expiration_time >= ten_minutes_from_now

    def for_ai(self, msg: Optional["Message"] = None) -> types.Part | types.File:
        if self.is_summary:
            return types.Part.from_text(text=f"\nFile Name: {self.filename}\nFile Type: {self.type.split('/')[0]}\nFile Summary: {self.content}")
        elif msg is None:
            raise TypeError("msg Paramiter of is not provided")

        # if self.type.startswith("text/"):
        #     return types.Part.from_text(text=f"\nFile Name: {self.filename}\nFile Content: {self.content.decode('utf-8')}") # type: ignore
        elif self.type.startswith("text/") or self.type.startswith(("image/", "video/") or self.type == "application/pdf"):
            # Use cloud URI if available, otherwise upload
            if self.cloud_uri and self.is_expiration_valid(self.cloud_uri.expiration_time):
                return self.cloud_uri  # type: ignore
            if self.type.startswith("image/"):
                prefix = "Processing Image:"
            if self.type.startswith("text/"):
                prefix = "Processing Text File:"
            elif self.type.startswith("video/"):
                prefix = "Processing Video:"
            else:
                prefix = "Processing PDF:"
            for attempt in range(config.MAX_RETRIES):
                msg.content.append(Content(text=f"{prefix} {self.filename}", processing=True))
                update_chat_message(msg)
                try:
                    self.cloud_uri = client.files.upload(file=BytesIO(self.content), config=types.UploadFileConfig(display_name=self.filename, mime_type = self.type))
                    # Check whether the file is ready to be used.
                    while self.cloud_uri.state.name == "PROCESSING":  # type: ignore
                        time.sleep(1)
                        self.cloud_uri = client.files.get(
                            name=self.cloud_uri.name)  # type: ignore
                    if self.cloud_uri.state.name == "FAILED":  # type: ignore
                        raise ValueError(self.cloud_uri.state.name)  # type: ignore
                    return self.cloud_uri
                except Exception:
                    if attempt < config.MAX_RETRIES - 1:
                        time.sleep(config.RETRY_DELAY)
                    else:
                        raise  # Re-raise the exception to be caught in completeChat
                finally:
                    msg.content.pop()
                    update_chat_message(msg)
        raise ValueError(f"Unsported File Type: {self.type} of file {self.filename}")

    def for_summarizer(self) -> list[types.Part]:
        if self.is_summary:
            return [self.for_ai()]
        if self.type.startswith("text/"):
            return [types.Part.from_text(text=f"\nname: {self.filename}\nid: {self.id}\nFile_Content: {self.content.decode('utf-8')}")]  # type: ignore
        elif self.type.startswith(("image/", "video/", "application/pdf")):
            if self.cloud_uri and self.is_expiration_valid(self.cloud_uri.expiration_time):
                return [types.Part.from_text(text=f"\nFileID: {self.id}"), self.cloud_uri]  # type: ignore
            for attempt in range(config.MAX_RETRIES):
                try:
                    self.cloud_uri = client.files.upload(file=BytesIO(self.content), config={  # type: ignore
                                                         "display_name": self.filename, "mime_type": self.type})
                    # Check whether the file is ready to be used.
                    while self.cloud_uri.state.name == "PROCESSING":  # type: ignore
                        time.sleep(1)
                        self.cloud_uri = client.files.get(
                            name=self.cloud_uri.name)  # type: ignore
                    if self.cloud_uri.state.name == "FAILED":  # type: ignore
                        raise ValueError(self.cloud_uri.state.name)  # type: ignore
                    return [types.Part.from_text(text=f"\nFileID: {self.id}"), self.cloud_uri]  # type: ignore
                except Exception:
                    if attempt < config.MAX_RETRIES - 1:
                        time.sleep(config.RETRY_DELAY)
                    else:
                        raise  # Re-raise the exception to be caught in completeChat
        raise ValueError(f"Unsported File Type: {self.type} of file {self.filename}")

    def jsonify(self) -> dict:
        return {
            "type": self.type,
            "filename": self.filename,
            "content": base64.b64encode(self.content).decode('utf-8', errors='ignore'),  # type: ignore
            "id": self.id,
            "is_summary": self.is_summary,
            "cloud_uri": self.cloud_uri.to_json_dict() if self.cloud_uri else None
        }

    @staticmethod
    def from_jsonify(data: dict):
        content = base64.b64decode(data.get('content', ''))
        return File(
            content,
            data.get('type', ''),
            data.get('filename', ''),
            types.File.model_validate(data.get('cloud_uri')) if data.get('cloud_uri') else None,
            data.get('id', ''),
            data.get('is_summary', False)
        )

class GroundingSupport:
    grounding_chunk_indices: list[int] = []
    # dict[{"start_index", int}, {"end_index", int}, {"text", str}]
    segment: dict[str, int | str] = {}

    def __init__(self,
                 grounding_chunk_indices: list[int],
                 # dict[{"start_index", int}, {"end_index", int}, {"text", str}]
                 segment: dict[str, int | str]
                 ):
        self.grounding_chunk_indices = grounding_chunk_indices
        self.segment = segment

    def jsonify(self) -> dict:
        return {
            "grounding_chunk_indices": self.grounding_chunk_indices,
            "segment": self.segment,
        }

    @staticmethod
    def from_jsonify(data: dict):
        return GroundingSupport(data.get("grounding_chunk_indices", []), data.get("segment", {}))

class GroundingMetaData:
    first_offset: int = 0
    rendered_content: str = ""
    # list[tuple[str: title, str: uri]]
    grounding_chuncks: list[tuple[str, str]] = []
    grounding_supports: list[GroundingSupport] = []

    def __init__(self,
                 grounding_chuncks: Optional[list[tuple[str, str]]] = None,
                 grounding_supports: Optional[list[GroundingSupport]] = None,
                 first_offset: Optional[int] = 0,
                 rendered_content: Optional[str] = "",
                 ):
        self.grounding_chuncks = grounding_chuncks if grounding_chuncks else []
        self.grounding_supports = grounding_supports if grounding_supports else []
        self.first_offset = first_offset if first_offset else 0
        self.rendered_content = rendered_content if rendered_content else ""

    def jsonify(self) -> dict[str, Any]:
        return {
            "first_offset": self.first_offset,
            "rendered_content": self.rendered_content,
            "grounding_chuncks": self.grounding_chuncks,
            "grounding_supports": [gsp.jsonify() for gsp in self.grounding_supports],
        }

    @staticmethod
    def from_jsonify(data: dict):
        return GroundingMetaData(data.get("grounding_chuncks", None),
                                 [GroundingSupport.from_jsonify(sup) for sup in data.get("grounding_supports", [])],
                                 data.get("first_offset", 0),
                                 data.get("rendered_content", ""))

class FunctionCall:
    id: str = ""
    name: Optional[str]
    args: dict[str, Any]

    def __init__(self, id: Optional[str] = None, name: Optional[str] = "", args: Optional[dict[str, Any]] = None):
        self.id = id if id else str(uuid.uuid4())
        self.name = name
        self.args = args if args else {}

    def for_ai(self) -> types.FunctionCall:
        return types.FunctionCall(
            id=self.id,
            name=self.name,
            args=self.args
        )

    def for_summarizer(self) -> list[types.Part]:
        return [
                types.Part(text=f"CallID: {self.id}"),
                types.Part(
                    function_call=types.FunctionCall(
                        id=self.id,
                        name=self.name,
                        args=self.args
                    )
                )
            ]

    def jsonify(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "args": self.args
        }

    @staticmethod
    def from_jsonify(data: dict[str, Any]) -> "FunctionCall":
        return FunctionCall(
            data.get("id"),
            data.get("name"),
            data.get("args")
        )

class FunctionResponce:
    id: str = ""
    name: Optional[str] = None
    response: dict[str, Any]

    def __init__(self, id: Optional[str] = None, name: Optional[str] = None, response: Optional[dict[str, Any]] = None):
        self.id = id if id else str(uuid.uuid4())
        self.name = name
        self.response = response if response else {}

    def for_ai(self) -> types.FunctionResponse:
        return types.FunctionResponse(
            id=self.id,
            name=self.name,
            response=self.response # type: ignore
        )

    def for_summarizer(self) -> list[types.Part]:
        return [
                types.Part(text=f"ResponceID: {self.id}"),
                types.Part(
                    function_response=types.FunctionResponse(
                        id=self.id,
                        name=self.name,
                        response=self.response
                    )
                )
            ]

    def jsonify(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "response": self.response
        }

    @staticmethod
    def from_jsonify(data: dict[str, Any]) -> "FunctionResponce":
        return FunctionResponce(
            data.get("id"),
            data.get("name", ""),
            data.get("response")
        )

class Content:
    text: Optional[str] = None
    processing: bool = False
    attachment: Optional[File] = None
    grounding_metadata: Optional[GroundingMetaData] = None
    function_call: Optional[FunctionCall] = None
    function_response: Optional[FunctionResponce] = None

    def __init__(
            self,
            text: Optional[str] = None,
            attachment: Optional[File] = None,
            grounding_metadata: Optional[GroundingMetaData] = None,
            processing: bool = False,
            function_call: Optional[FunctionCall] = None,
            function_response: Optional[FunctionResponce] = None,
        ):
        self.text = text
        self.attachment = attachment
        self.grounding_metadata = grounding_metadata
        self.processing = processing
        self.function_call = function_call
        self.function_response = function_response

    def for_ai(self, suport_tools: bool, msg: Optional["Message"] = None) -> types.Part | types.File | None:
        if self.function_call and suport_tools:
            return types.Part(function_call=self.function_call.for_ai())
        elif self.function_response and suport_tools:
            return types.Part(function_response=self.function_response.for_ai())
        elif self.text:
            return types.Part(text=self.text)
        elif self.attachment is not None:
            return self.attachment.for_ai(msg)

    def for_sumarizer(self) -> list[types.Part]:
        if self.function_call:
            return self.function_call.for_summarizer()
        elif self.function_response:
            return self.function_response.for_summarizer()
        elif self.text:
            return [types.Part(text=self.text)]
        elif self.attachment is not None:
            return self.attachment.for_summarizer()
        else:
            return []

    def jsonify(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "attachment": self.attachment.jsonify() if self.attachment else None,
            "grounding_metadata": self.grounding_metadata.jsonify() if self.grounding_metadata else None,
            "processing": self.processing,
            "function_call": self.function_call.jsonify() if self.function_call else None,
            "function_response": self.function_response.jsonify() if self.function_response else None,
        }

    @staticmethod
    def from_jsonify(data: dict[str, Any]) -> "Content":
        return Content(
            text=data.get("text", ""),
            attachment=File.from_jsonify(data["attachment"]) if data.get("attachment") else None,
            grounding_metadata=GroundingMetaData.from_jsonify(data["grounding_metadata"]) if data.get("grounding_metadata") else None,
            function_call=FunctionCall.from_jsonify(data["function_call"]) if data.get("function_call") else None,
            function_response=FunctionResponce.from_jsonify(data["function_response"]) if data.get("function_response") else None,
        )

class Message:
    role: Literal["model", "user"]
    content: list[Content]
    thought: str
    time_stamp: datetime.datetime
    id: str
    is_summary: bool

    def __init__(self, content: list[Content], role: Literal["model", "user"], time_stamp: Optional[datetime.datetime] = None, is_summary: bool = False, id: Optional[str] = None, thought: str = ""):
        self.time_stamp = time_stamp if time_stamp else datetime.datetime.now()
        self.content = content
        self.role = role
        self.id = str(uuid.uuid4()) if id is None else id
        self.is_summary = is_summary
        self.thought = thought

    def delete(self) -> None:
        for item in self.content:
            if item.attachment:
                item.attachment.delete()

    def get_attachment(self, ID: str) -> File:
        for item in self.content:
            if item.attachment:
                if item.attachment.id == ID:
                    return item.attachment
        raise ValueError(f"Attachment with ID `{ID}` not found in message `{self.id}`.")

    def delete_attachment(self, ID: str):
        for idx, item in enumerate(self.content):
            if item.attachment:
                if item.attachment.id == ID:
                    item.attachment.delete()
                    del self.content[idx]
                    return

    def get_func_call(self, ID: str) -> FunctionCall:
        for item in self.content:
            if item.function_call:
                if item.function_call.id == ID:
                    return item.function_call
        raise ValueError(f"Function Call with ID `{ID}` not found in message `{self.id}`.")

    def delete_func_call(self, ID: str):
        for idx, item in enumerate(self.content):
            if item.function_call:
                if item.function_call.id == ID:
                    del self.content[idx]
                    return

    def get_func_responce(self, ID: str) -> FunctionResponce:
        for item in self.content:
            if item.function_response:
                if item.function_response.id == ID:
                    return item.function_response
        raise ValueError(f"Function Responce with ID `{ID}` not found in message `{self.id}`.")

    def delete_func_responce(self, ID: str):
        for idx, item in enumerate(self.content):
            if item.function_response:
                if item.function_response.id == ID:
                    del self.content[idx]
                    return

    def for_ai(self, suport_tools: bool, msg: Optional["Message"] = None) -> list[types.Content]:
        if self.is_summary:
            return [types.Content(parts=[content.for_ai(msg) for content in self.content], role=self.role)]  # type: ignore
        if msg is None:
            raise ValueError("msg parameter is required.")

        ai_contents: list[types.Content] = []
        parts_buffer = [types.Part(text=self.time_stamp.strftime("%H:%M"))]

        for item in self.content:
            if item.function_response:
                if parts_buffer:
                    ai_contents.append(types.Content(parts=parts_buffer, role=self.role))
                    parts_buffer = []
                if (part := item.for_ai(suport_tools, msg)) and msg and self.id == msg.id:
                    ai_contents.append(types.Content(parts=[part], role="user"))
                    ai_contents.append(types.Content(parts=[types.Part(text=self.time_stamp.strftime("%H:%M"))], role="model"))
                elif part := item.for_ai(suport_tools, msg):
                    ai_contents.append(types.Content(parts=[part], role="user"))
            elif part := item.for_ai(suport_tools, msg):
                if isinstance(part, types.Part):
                    parts_buffer.append(part)
                else:
                    if parts_buffer:
                        ai_contents.append(types.Content(parts=parts_buffer, role=self.role))
                        parts_buffer = []
                    ai_contents.append(part) # type: ignore

        if parts_buffer:
            ai_contents.append(types.Content(parts=parts_buffer, role=self.role))

        return ai_contents

    def for_summarizer(self) -> list[types.Content]:
        ai_contents: list[types.Content] = []
        parts_buffer: list[types.Part] = [
            types.Part.from_text(text=f"MessageID: {self.id}"),
            types.Part.from_text(text=self.time_stamp.strftime("on %d-%m-%Y at %H")),
        ]

        for item in self.content:
            if item.function_response:
                if parts_buffer:
                    ai_contents.append(types.Content(parts=parts_buffer, role=self.role))
                    parts_buffer = []
                ai_contents.append(types.Content(parts=item.for_sumarizer(), role="user"))
            else:
                parts_buffer.extend(item.for_sumarizer())

        if parts_buffer:
            ai_contents.append(types.Content(parts=parts_buffer, role=self.role))

        return ai_contents

    def jsonify(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "content": [item.jsonify() for item in self.content],
            "id": self.id,
            "time_stamp": self.time_stamp.isoformat(),
            "is_summary": self.is_summary,
            "thought": self.thought,
        }

    @staticmethod
    def from_jsonify(data: dict):
        return Message(
            content=[Content.from_jsonify(item) for item in data.get("content", [])],
            role=data["role"],
            time_stamp=datetime.datetime.fromisoformat(data["time_stamp"]),
            is_summary=data.get("is_summary", False),
            id=data.get("id", ""),
            thought=data.get("thought", ""),
        )

class ChatHistory:
    __chat: list[Message] = []

    def append(self, msg: Message):
        self.__chat.append(msg)
        socketio.emit("add_message", msg.jsonify())

    def delete_message(self, msg_id):
        self.__chat = [msg for msg in self.__chat if msg.id != msg_id]
        delete_chat_message(msg_id)

    def __len__(self):
        return len(self.__chat)

    def __getitem__(self, idx: int):
        return self.__chat[idx]

    def getMsg(self, ID: str) -> Message:
        for msg in self.__chat:
            if msg.id == ID:
                return msg
        raise ValueError(f"Message of ID: `{ID}` not found")

    def setMsg(self, ID: str, new_msg: Message):
        for msg in self.__chat:
            if msg.id == ID:
                msg = new_msg
                update_chat_message(msg)
                return
        raise ValueError(f"Message of ID: `{ID}` not found")

    def getMsgRange(self, Start_ID: str, End_ID: str) -> Iterator[Message]:
        idx = 0
        while idx < len(self.__chat):
            if self.__chat[idx].id == Start_ID:
                while idx < len(self.__chat):
                    if self.__chat[idx].id == End_ID:
                        return self.__chat[idx]
                    else:
                        yield self.__chat[idx]
                        idx += 1
                raise ValueError(f"Message of ID: `{End_ID}` not found")
            idx += 1
        raise ValueError(f"Message of ID: `{Start_ID}` not found")

    def delMsgRange(self, Start_ID: str, End_ID: str) -> None:
        """Ignore Start_ID msg, delete from Start_ID+1..End_ID"""
        idx = 0
        while idx < len(self.__chat):
            if self.__chat[idx].id == Start_ID:
                while idx < len(self.__chat):
                    delete_chat_message(self.__chat[idx].id)
                    del self.__chat[idx]
                    if self.__chat[idx].id == End_ID:
                        return
                    else:
                        idx += 1
                raise ValueError(f"Message of ID: `{End_ID}` not found")
            idx += 1
        raise ValueError(f"Message of ID: `{Start_ID}` not found")

    def replaceMsgRange(self, Start_ID: str, End_ID: str, msg: Message) -> None:
            idx = 0
            while idx < len(self.__chat):
                if self.__chat[idx].id == Start_ID:
                    self.__chat[idx] = msg
                    update_chat_message(msg)
                    idx += 1
                    while idx < len(self.__chat):
                        del self.__chat[idx]
                        delete_chat_message(self.__chat[idx].id)
                        if self.__chat[idx].id == End_ID:
                            return
                        else:
                            idx += 1
                    raise ValueError(f"Message of ID: `{End_ID}` not found")
                idx += 1
            raise ValueError(f"Message of ID: `{Start_ID}` not found")

    def tripAfter(self, msg_ID: str) -> None:
        idx: int = 0
        for i, msg in enumerate(self.__chat):
            if msg.id == msg_ID:
                idx = i
                break
        for i in range(idx + 1, len(self.__chat)):
            delete_chat_message(self.__chat[i].id)
        self.__chat = self.__chat[:idx + 1]

    def for_ai(self, ai_msg: Message, suport_tools: bool) -> list[types.Content]:
        result: list[types.Content] = []
        for msg in self.__chat:
            result.extend(msg.for_ai(suport_tools, ai_msg))
        return result

    def for_summarizer(self) -> list[types.Content]:
        result: list[types.Content] = []
        for msg in self.__chat:
            result.extend(msg.for_summarizer())
        return result

    def jsonify(self) -> list[dict[str, str | Literal["model", "user"] | list]]:
        return [msg.jsonify() for msg in self.__chat]

    def save_to_json(self, filepath: str):
        """Saves the chat history to a JSON file."""
        data = [msg.jsonify() for msg in self.__chat]
        with open(filepath, 'w') as f:
            json.dump(data, f, indent=4)

    def load_from_json(self, filepath: str):
        """Loads the chat history from a JSON file."""
        try:
            with open(filepath, 'r') as f:
                data = json.load(f)
                self.__chat = []
                for msg_data in data:
                    msg = Message.from_jsonify(msg_data)
                    self.__chat.append(msg)
        except FileNotFoundError:
            print("Chat history file not found. Starting with an empty chat.")
        except json.JSONDecodeError:
            print("Error decoding chat history. Starting with an empty chat.")
#endregion

#region Chat History Management

chat_history: ChatHistory = ChatHistory()

def complete_chat(message: str, files: Optional[list[File]] = None):
    """
    Appends user message to chat history, gets AI response, and handles grounding metadata.
    """
    if files is None:
        files = []

    # Append user message if there's content
    if message or files:
        append_user_message(message, files)

    # Get AI response and update chat history
    ai_response = get_ai_response()

    if ai_response:
        update_chat_message(ai_response)

def append_user_message(message: str, files: list[File]):
    """Appends the user's message and files to the chat history."""
    chat_history.append(Message([Content(message), *(Content(attachment=file) for file in files)], "user", datetime.datetime.now()))

def get_ai_response() -> Message:
    """
    Gets the AI's response from the Gemini model, handling retries and token limits.
    """
    # Append a placeholder for the AI reply
    chat_history.append(Message([], "model"))
    msg = chat_history[len(chat_history) - 1]
    try:
        return generate_content_with_retry(msg)
    except Exception as e:
        handle_generation_failure(msg, e)
        return msg

def update_chat_message(msg: Message):
    """
    emits the updated message.
    """
    socketio.emit("updated_msg", msg.jsonify())

def delete_chat_message(msg_id: str):
    """
    emits the delete message.
    """
    socketio.emit("delete_message", msg_id)
#endregion

#region Gemini Model Interaction
@utils.retry()
def generate_content_with_retry(msg: Message) -> Message:
    """
    Generates content from Gemini, retrying on token limits or other errors.

    Args:
        msg: Message object to be populated with generated content

    Returns:
        Populated Message object with generated content
    """
    # Helper function to handle streaming content parts
    def handle_part(part: types.Part):
        # Mark previous content as no longer processing if exists
        if msg.content and msg.content[-1].text is not None:
            msg.content[-1].processing = False

        # Handle thought content
        if part.thought and part.text:
            msg.thought += part.text

        # Handle regular text content
        elif part.text:
            # Create initial content if none exists
            if not msg.content:
                msg.content.append(Content(text="", processing=True))

            # Add new content or append to existing
            if msg.content[-1].text is None:
                msg.content.append(Content(text=part.text))
            else:
                msg.content[-1].text += part.text

        # Handle function calls
        elif part.function_call:
            handle_function_call(part.function_call)

    # Helper function to handle function calls and responses
    def handle_function_call(func_call: types.FunctionCall):
        # Add function call to message content
        msg.content.append(Content(
            function_call=FunctionCall(
                id=func_call.id,
                name=func_call.name,
                args=func_call.args
            )
        ))

        try:
            # Validate function name
            if not func_call.name:
                raise ValueError("Function with no name specified")

            # Call the appropriate tool function and add response
            if func_call.args:
                func_response = getattr(tools, func_call.name)(**func_call.args)
            else:
                func_response = getattr(tools, func_call.name)()

            # Add successful function response
            msg.content.append(Content(
                function_response=FunctionResponce(
                    id=msg.content[-1].function_call.id, # type: ignore
                    name=func_call.name,
                    response={"output": func_response}
                )
            ))

        except Exception as e:
            # Add error response with detailed exception info
            error_msg = f"Error executing {func_call.name}: {str(e)}"
            msg.content.append(Content(
                function_response=FunctionResponce(
                    id=msg.content[-1].function_call.id, # type: ignore
                    name=func_call.name or "unknown_function",
                    response={"error": error_msg}
                )
            ))
            print(error_msg)

    @utils.retry(exceptions=(ValueError, AttributeError, ConnectionError))
    def get_model_and_tools() -> tuple[str, bool, list[types.Tool]]:
        """
        Determines which model and tools to use, with retry logic.

        Returns:
            Tuple of (model_name, tools_list)

        Raises:
            Exception: If selection fails after multiple attempts
        """
        chat = chat_history.for_ai(msg, True)
        global model
        allowed_function_names: Optional[list[str]] = None
        # Case 1: Both model and tools are already selected
        if model is not None and selected_tools is not None:
            return config.Models[model].value, model in config.ToolSuportedModels, [tools.Tools[selected_tool].value for selected_tool in selected_tools]

        # Case 2: Only model is selected, need to select tools
        elif model is not None:
            if model in config.SearchGroundingSuportedModels:
                chat.append(types.Content(
                    parts=[types.Part(text="Select which tools to use to reply to the user message.")],
                    role="user"
                ))
                tools_list = [types.Tool(
                    function_declarations=[types.FunctionDeclaration.from_callable_with_api_option(
                        callable=tools.ToolSelector
                    )]
                )]
                allowed_function_names = [tools.ToolSelector.__name__]
            elif model in config.ToolSuportedModels:
                chat.append(types.Content(
                    parts=[types.Part(
                        text=f"Select which tools to use to reply to the user message. "
                             f"Important: Don't use `Search` tool as it's not supported by the current model."
                    )],
                    role="user"
                ))
                tools_list = [types.Tool(
                    function_declarations=[types.FunctionDeclaration.from_callable_with_api_option(
                        callable=tools.ToolSelector
                    )]
                )]
                allowed_function_names = [tools.ToolSelector.__name__]
            else:
                return config.Models[model].value, model in config.ToolSuportedModels, []

        # Case 3: Only tools are selected, need to select model
        elif selected_tools is not None:
            if tools.Tools.SearchGrounding.name in selected_tools:
                chat.append(types.Content(
                    parts=[types.Part(
                        text=f"Select which model to use to reply to the user message. "
                             f"Important: Use only these models: {config.SearchGroundingSuportedModels} "
                             f"as they are the only ones that support `SearchGrounding`."
                    )],
                    role="user"
                ))
            else:
                chat.append(types.Content(
                    parts=[types.Part(
                        text=f"Select which model to use to reply to the user message. "
                             f"Important: Use only these models: {config.ToolSuportedModels} "
                             f"as they are the only ones that support Tool Calling."
                    )],
                    role="user"
                ))
            tools_list = [types.Tool(
                function_declarations=[types.FunctionDeclaration.from_callable_with_api_option(
                    callable=tools.ModelSelector
                )]
            )]
            allowed_function_names = [tools.ModelSelector.__name__]

        # Case 4: Neither model nor tools selected, need to select both
        else:
            chat.append(types.Content(
                parts=[types.Part(text=f"Select which model and tools to use to reply to the user message.")],
                role="user"
            ))
            tools_list = [types.Tool(
                function_declarations=[types.FunctionDeclaration.from_callable_with_api_option(
                    callable=tools.ModelAndToolSelector
                )]
            )]
            allowed_function_names = [tools.ModelAndToolSelector.__name__]

        # Try selection process with multiple attempts
        for attempt in range(3):
            try:
                # Make selection request to tool selector model
                selector_response = client.models.generate_content(
                    model=config.MODEL_TOOL_SELECTOR,
                    contents=chat,  # type: ignore
                    config=types.GenerateContentConfig(
                        system_instruction=prompt.ModelAndToolSelectorSYSTEM_INSTUNCTION,
                        temperature=0.1,
                        tools=tools_list,  # type: ignore
                        automatic_function_calling=types.AutomaticFunctionCallingConfig(
                            disable=True,
                            maximum_remote_calls=None
                        ),
                        tool_config=types.ToolConfig(
                            function_calling_config=types.FunctionCallingConfig(mode=types.FunctionCallingConfigMode.ANY,
                            allowed_function_names=allowed_function_names)
                        )
                    )
                )

                # Process response if function calls are present
                if selector_response.function_calls and selector_response.function_calls[0].args:
                    call_name = selector_response.function_calls[0].name
                    args = selector_response.function_calls[0].args
                    call_id = selector_response.function_calls[0].id

                    # Handle tool selection when model is known
                    if call_name == "ToolSelector" and model is not None:
                        try:
                            return config.Models[model].value, model in config.ToolSuportedModels, tools.ToolSelector(**args)
                        except Exception as e:
                            handle_selector_error(chat, call_id, call_name, e)
                            continue

                    # Handle model selection when tools are known
                    elif call_name == "ModelSelector" and selected_tools is not None:
                        try:
                            return tools.ModelSelector(**args), model in config.ToolSuportedModels, tools.ToolSelector(selected_tools)
                        except Exception as e:
                            handle_selector_error(chat, call_id, call_name, e)
                            continue

                    # Handle combined model and tool selection
                    elif call_name == "ModelAndToolSelector":
                        try:
                            return tools.ModelAndToolSelector(**args)
                        except Exception as e:
                            handle_selector_error(chat, call_id, call_name, e)
                            continue

                    # Handle unknown function call
                    else:
                        error_msg = f"Unknown function: {call_name}"
                        handle_selector_error(chat, call_id, call_name, error_msg)
                        continue

                # No function calls detected
                else:
                    chat.append(types.Content(
                        parts=[types.Part(
                            text=f"Select which model and tools to use to reply to the user message. "
                                 f"You didn't call the required function."
                        )],
                        role="user"
                    ))
                    continue

            except Exception as e:
                # Log error and continue to next attempt
                print(f"Selection attempt {attempt+1} failed: {str(e)}")
                if attempt == 2:  # Last attempt
                    raise Exception(f"Failed to select model and tools after multiple attempts: {str(e)}")

        # If we reach here, all attempts failed
        raise Exception("Cannot select models & tools automatically. Please select manually.")

    # Helper function to handle selector errors
    def handle_selector_error(chat, call_id, call_name, error):
        error_msg = f"Error occurred while calling function: {error}"
        chat.append(types.Content(
            parts=[types.Part(
                function_response=types.FunctionResponse(
                    id=call_id,
                    name=call_name,
                    response={"error": error_msg}
                )
            )],
            role="user"
        ))
        print(error_msg)

    # Main execution flow
    try:
        # Get model and tools
        selected_model, suports_tools, selected_tools_list = get_model_and_tools()
        print(f"Using model: {selected_model} with tools: {selected_tools_list}")

        # Main content generation loop
        while True:
            try:
                start_time = time.time()  # Record start time before request
                # Generate streaming content
                response = client.models.generate_content_stream(
                    model=selected_model,
                    contents=chat_history.for_ai(msg, suports_tools),  # type: ignore
                    config=types.GenerateContentConfig(
                        system_instruction=prompt.SYSTEM_INSTUNCTION + tools.get_reminders(),
                        temperature=config.CHAT_AI_TEMP,
                        tools=selected_tools_list,  # type: ignore
                        automatic_function_calling=types.AutomaticFunctionCallingConfig(
                            disable=True,
                            maximum_remote_calls=None
                        ),
                        # thinking_config=types.ThinkingConfig(include_thoughts=True) # Not suported till now
                    )
                )

                # Process the streaming response
                function_call_occurred = False
                finish_region: types.FinishReason | None = None
                for content in response:
                    if (content.candidates and
                        content.candidates[0].content and
                        content.candidates[0].content.parts):

                        for part in content.candidates[0].content.parts:
                            handle_part(part)
                            if part.function_call:
                                function_call_occurred = True
                                print(f"Function call detected: {part.function_call}")
                    if content.candidates and content.candidates[0].finish_reason:
                        finish_region = content.candidates[0].finish_reason

                    # Process additional metadata
                    process_grounding_metadata(msg, content)
                    update_chat_message(msg)

                # Mark processing as complete
                if msg.content:
                    msg.content[-1].processing = False
                    update_chat_message(msg)

                # sleep for some time if needed
                end_time = time.time()  # Record end time after response processing
                elapsed_time = end_time - start_time  # Calculate elapsed time

                if function_call_occurred or finish_region == types.FinishReason.MAX_TOKENS:
                    rpm_limit = config.model_RPM_map.get(selected_model, 1)  # Get RPM limit, default to 1 if not found
                    target_delay_per_request_sec = 60.0 / rpm_limit  # Calculate target delay in seconds
                    print(f"{target_delay_per_request_sec=}")
                    print(f"{elapsed_time=}")
                    sleep_duration = max(0, target_delay_per_request_sec - elapsed_time) # Calculate sleep duration, ensure it's not negative
                    print(f"{sleep_duration=}")
                    if sleep_duration > 0:
                        print(f"Sleeping for {sleep_duration:.2f} seconds to respect RPM limit.")
                        time.sleep(sleep_duration)  # Sleep to respect RPM limit
                    continue

                # Otherwise break the loop
                break

            except Exception as e:
                error_msg = f"Error during content generation: {str(e)}"
                print(error_msg)

                # Add error message to content if appropriate
                if not msg.content:
                    msg.content.append(Content(text=f"An error occurred: {str(e)}"))
                elif msg.content[-1].text is None:
                    msg.content.append(Content(text=f"An error occurred: {str(e)}"))
                else:
                    msg.content[-1].text += f"\n\nAn error occurred: {str(e)}"

                # Mark as not processing and update
                if msg.content:
                    msg.content[-1].processing = False
                    update_chat_message(msg)

                # Decide whether to retry based on error type
                if isinstance(e, (ConnectionError, TimeoutError)):
                    print(f"Retrying after error: {str(e)}")
                    continue
                else:
                    # Non-retryable error
                    break

    except Exception as e:
        # Handle any unexpected errors in the overall process
        error_msg = f"Fatal error in content generation: {str(e)}"
        print(error_msg)

        if not msg.content:
            msg.content.append(Content(text=f"Failed to generate content: {str(e)}"))

        if msg.content and msg.content[-1].processing:
            msg.content[-1].processing = False
            update_chat_message(msg)

    # Set timestamp and return message
    msg.time_stamp = datetime.datetime.now()
    return msg

def process_grounding_metadata(msg: Message, content: types.GenerateContentResponse):
    """
    Processes grounding metadata from the AI response.
    """
    if content.candidates and content.candidates[0].grounding_metadata:
        metadata = content.candidates[0].grounding_metadata
        if msg.content[-1].grounding_metadata is None:
            msg.content[-1].grounding_metadata = GroundingMetaData([], [])
        if metadata.search_entry_point:
            msg.content[-1].grounding_metadata.rendered_content = metadata.search_entry_point.rendered_content or ""

        if metadata.grounding_chunks:
            for chunk in metadata.grounding_chunks:
                if chunk.web:
                    msg.content[-1].grounding_metadata.grounding_chuncks.append((chunk.web.title or "unknown", chunk.web.uri or ""))

        if metadata.grounding_chunks and metadata.grounding_supports and metadata.web_search_queries:
            process_grounding_supports(msg, metadata)
    update_chat_message(msg)

def process_grounding_supports(msg: Message, metadata: types.GroundingMetadata):
    """
    Processes grounding support information and updates the message.
    """
    if msg.content[-1].text is None:
        return
    if msg.content[-1].grounding_metadata is None:
        msg.content[-1].grounding_metadata = GroundingMetaData([], [])
    first = True
    for support in metadata.grounding_supports:  # type: ignore
        if support.segment and support.segment.text:
            start_index = msg.content[-1].text.find(support.segment.text)
            if start_index == -1:
                escaped_target = re.escape(msg.content[-1].text or "")
                # Create a regex pattern that allows for extra spaces and minor variations
                # Allow any amount of whitespace between chars
                # cz Gemini Grounding Suks
                pattern = r'\s*'.join(list(escaped_target))
                match = re.search(
                    pattern, support.segment.text or "")  # type: ignore
                if match:
                    return match.start()
                else:
                    continue

            if first:
                msg.content[-1].grounding_metadata.first_offset = start_index - \
                    support.segment.start_index  # type: ignore
                first = False

            msg.content[-1].grounding_metadata.grounding_supports.append(
                GroundingSupport(support.grounding_chunk_indices, {  # type: ignore
                    "text": support.segment.text,  # type: ignore
                    "start_index": start_index,
                    "end_index": start_index + len(support.segment.text) # type: ignore
                })  # type: ignore
            )
    update_chat_message(msg)

def handle_generation_failure(msg: Message, error: Exception):
    """
    Handles the failure to generate a response from the AI model.
    """
    import traceback
    error_message = f"Failed to generate response after multiple retries: {str(error)}\n\nTraceback:\n```\n{traceback.format_exc()}\n```"
    if not msg.content or msg.content[-1].text is None:
        msg.content.append(Content(text=error_message))
    else:
        msg.content[-1].text = error_message
    update_chat_message(msg)

#endregion

#region Token Reduction (Summarization/Removal)

@utils.retry(exceptions=(ConnectionError, TimeoutError, ValueError))
def SummarizeAttachment(AttachmentID: str, MessageID: str):
    """
    Summarizes the content of a specific attachment, linking the summary to the original attachment and message.

    Use this for attachments that are no longer actively referenced but might contain valuable background information.

    Args:
        AttachmentID: The ID of the attachment to summarize
        MessageID: The ID of the message containing the attachment

    Returns:
        str: Status message indicating success or failure
    """
    try:
        # Prepare the chat content for summarization
        chat: list[types.Content] = [
            types.Content(
                role="user",
                parts=[
                    *chat_history.getMsg(MessageID).get_attachment(AttachmentID).for_summarizer(),
                    types.Part.from_text(
                        text="Summarize the above file attachment while preserving the details and facts")
                ]
            ),
            types.Content(
                role="model",
                parts=[
                    types.Part.from_text(
                        text="Attachment summary:\n")
                ]
            )
        ]

        # Generate the summary content
        response = client.models.generate_content(
            model=config.SUMMARIZER_AI,
            contents=chat, # type: ignore
            config=types.GenerateContentConfig(
                system_instruction=prompt.ATTACHMENT_SUMMARIZER_SYSTEM_INSTUNCTION,
                temperature=0,
            )
        )

        # Update the attachment with the summary
        msg = chat_history.getMsg(MessageID)
        file = msg.get_attachment(AttachmentID)
        file.is_summary = True

        if response.text:
            file.content = response.text
            update_chat_message(msg)
            return f"Successfully summarized attachment: {AttachmentID=}, {MessageID=}"
        else:
            return f"Failed to summarize attachment (empty response): {AttachmentID=}, {MessageID=}"

    except Exception as e:
        return f"Error summarizing attachment: {AttachmentID=}, {MessageID=}. Error: {str(e)}"


@utils.retry(exceptions=(ConnectionError, TimeoutError, ValueError))
def SummarizeMessage(MessageID: str):
    """
    Summarizes the content of a specific message with its attachments.

    Use this for verbose or lengthy messages that contain information that can be condensed
    without losing critical meaning.

    Args:
        MessageID: The ID of the message to summarize

    Returns:
        str: Status message indicating success or failure
    """
    try:
        # Prepare the chat content for summarization
        chat: list[types.Content] = [
            *chat_history.getMsg(MessageID).for_summarizer(),
            types.Content(
                role="user",
                parts=[
                    types.Part.from_text(
                        text="Summarize the above message with its attachments while preserving the details and facts")
                ]
            ),
            types.Content(
                role="model",
                parts=[
                    types.Part.from_text(
                        text="Message with its attachment summary:\n")
                ]
            )
        ]

        # Generate the summary content
        response = client.models.generate_content(
            model=config.SUMMARIZER_AI,
            contents=chat, # type: ignore
            config=types.GenerateContentConfig(
                system_instruction=prompt.MESSAGE_SUMMARIZER_SYSTEM_INSTUNCTION,
                temperature=0,
            )
        )

        # Update the message with the summary
        msg = chat_history.getMsg(MessageID)
        msg.is_summary = True

        if response.text:
            if not msg.content or msg.content[-1].text is None:
                msg.content.append(Content(text=response.text))
            else:
                msg.content[-1].text += response.text

            update_chat_message(msg)
            return f"Successfully summarized message: {MessageID}"
        else:
            return f"Failed to summarize message (empty response): {MessageID}"

    except Exception as e:
        return f"Error summarizing message: {MessageID}. Error: {str(e)}"


@utils.retry(exceptions=(ConnectionError, TimeoutError, ValueError))
def SummarizeHistory(StartMessageID: str, EndMessageID: str):
    """
    Summarizes a range of messages within StartMessageID & EndMessageID (inclusive).

    Use this for older conversations that are no longer directly relevant but provide useful context.

    Args:
        StartMessageID: The ID of the first message in the range to summarize
        EndMessageID: The ID of the last message in the range to summarize

    Returns:
        str: Status message indicating success or failure
    """
    try:
        # Get messages for summarization
        messages = []
        for msg in chat_history.getMsgRange(StartMessageID, EndMessageID):
            messages.extend(msg.for_summarizer())

        # Prepare the chat content for summarization
        chat: list[types.Content] = [
            *messages,
            types.Content(
                role="user",
                parts=[
                    types.Part.from_text(
                        text="Summarize the above messages with their attachments while preserving the details and facts")
                ]
            ),
            types.Content(
                role="model",
                parts=[
                    types.Part.from_text(
                        text="Message & its attachment history summary:\n")
                ]
            )
        ]

        # Generate the summary content
        response = client.models.generate_content(
            model=config.SUMMARIZER_AI,
            contents=chat, # type: ignore
            config=types.GenerateContentConfig(
                system_instruction=prompt.MESSAGE_HISTORY_SUMMARIZER_SYSTEM_INSTUNCTION,
                temperature=0,
            )
        )

        if response.text:
            # Replace the range of messages with a summary
            chat_history.replaceMsgRange(
                StartMessageID,
                EndMessageID,
                Message([Content(text=response.text)], "user")
            )
            return f"Successfully summarized messages from {StartMessageID} to {EndMessageID}"
        else:
            return f"Failed to summarize messages (empty response) from {StartMessageID} to {EndMessageID}"

    except Exception as e:
        return f"Error summarizing message history: {StartMessageID} to {EndMessageID}. Error: {str(e)}"


def RemoveAttachment(AttachmentID: str, MessageID: str):
    """
    Removes a specific attachment from a message.

    Use this for attachments that are clearly irrelevant to the current conversation or have become obsolete.

    Args:
        AttachmentID: The ID of the attachment to remove
        MessageID: The ID of the message containing the attachment

    Returns:
        str: Status message indicating success
    """
    try:
        msg = chat_history.getMsg(MessageID)
        msg.delete_attachment(AttachmentID)
        update_chat_message(msg)
        return f"Successfully removed attachment: {AttachmentID=}, {MessageID=}"
    except Exception as e:
        return f"Error removing attachment: {AttachmentID=}, {MessageID=}. Error: {str(e)}"


def RemoveFunctionCall(FunctionCallID: str, MessageID: str):
    """
    Removes a specific function call from a message.

    Use this for function calls that are no longer relevant.

    Args:
        FunctionCallID: The ID of the function call to remove
        MessageID: The ID of the message containing the function call

    Returns:
        str: Status message indicating success
    """
    try:
        msg = chat_history.getMsg(MessageID)
        msg.delete_func_call(FunctionCallID)  # Assumes this method exists, corrected from delete_attachment
        update_chat_message(msg)
        return f"Successfully removed function call: {FunctionCallID=}, {MessageID=}"
    except Exception as e:
        return f"Error removing function call: {FunctionCallID=}, {MessageID=}. Error: {str(e)}"


def RemoveFunctionResponse(FunctionCallID: str, MessageID: str):
    """
    Removes a specific function response from a message.

    Use this for function responses that are no longer relevant.

    Args:
        FunctionCallID: The ID of the function response to remove
        MessageID: The ID of the message containing the function response

    Returns:
        str: Status message indicating success
    """
    try:
        msg = chat_history.getMsg(MessageID)
        msg.delete_func_responce(FunctionCallID)  # Assumes this method exists, corrected from delete_attachment
        update_chat_message(msg)
        return f"Successfully removed function response: {FunctionCallID=}, {MessageID=}"
    except Exception as e:
        return f"Error removing function response: {FunctionCallID=}, {MessageID=}. Error: {str(e)}"


def RemoveMessage(MessageID: str):
    """
    Removes an entire message from the chat history & its attachments.

    Use this sparingly and only for messages that are demonstrably irrelevant and contribute
    little to the overall context. If user asks AI about something & the current chat is
    irrelevant to it, then use this function.

    Args:
        MessageID: The ID of the message to remove

    Returns:
        str: Status message indicating success
    """
    try:
        chat_history.delete_message(MessageID)
        return f"Successfully removed message: {MessageID=}"
    except Exception as e:
        return f"Error removing message: {MessageID=}. Error: {str(e)}"


def RemoveMessageHistory(StartMessageID: str, EndMessageID: str):
    """
    Removes a range of messages within and including StartMessageID & EndMessageID.

    Use this for older conversations that are demonstrably irrelevant and contribute
    little to the overall context.

    Args:
        StartMessageID: The ID of the first message in the range to remove
        EndMessageID: The ID of the last message in the range to remove

    Returns:
        str: Status message indicating success
    """
    try:
        chat_history.delMsgRange(StartMessageID, EndMessageID)
        return f"Successfully removed message range: {StartMessageID=} to {EndMessageID=}"
    except Exception as e:
        return f"Error removing message range: {StartMessageID=} to {EndMessageID=}. Error: {str(e)}"


@socketio.on("shrink_chat")
def reduceTokensUsage():
    """
    Reduces token usage of the chat history by summarizing or removing content.

    Uses a model to determine which parts of the chat history to summarize or remove
    to reduce token usage while preserving important information.

    Returns:
        bool: True on success, False on failure.
    """
    # Map function names to their implementations
    function_map = {
        "SummarizeAttachment": SummarizeAttachment,
        "SummarizeMessage": SummarizeMessage,
        "SummarizeHistory": SummarizeHistory,
        "RemoveAttachment": RemoveAttachment,
        "RemoveMessage": RemoveMessage,
        "RemoveMessageHistory": RemoveMessageHistory,
        "RemoveFunctionCall": RemoveFunctionCall,
        "RemoveFunctionResponse": RemoveFunctionResponse  # Fixed typo in function name
    }

    # Create initial chat history for token reduction planning
    chat = chat_history.for_summarizer()
    chat.append(types.Content(
        parts=[types.Part(text=prompt.TOKEN_REDUCER_USER_INSTUNCTION)],
        role="user"
    ))

    # Retry loop
    for attempt in range(config.MAX_RETRIES):
        try:
            # Main processing loop
            while True:
                # Generate plan for token reduction
                response = client.models.generate_content(
                    model=config.TOKEN_REDUCER_PLANER,
                    contents=chat,  # type: ignore
                    config=types.GenerateContentConfig(
                        system_instruction=prompt.TOKEN_REDUCER_SYSTEM_INSTUNCTION,
                        temperature=0,
                        tools=list(function_map.values()),
                        automatic_function_calling=types.AutomaticFunctionCallingConfig(
                            disable=True,
                            maximum_remote_calls=None
                        ),
                    ),
                )

                # Process response
                content = types.Content(role="user", parts=[])
                execution_occurred = False

                # Handle each part of the response
                for part in response.candidates[0].content.parts:  # type: ignore
                    # Handle function calls
                    if part.function_call:
                        execution_occurred = True
                        function_name = part.function_call.name
                        function = function_map.get(function_name or "")

                        if function and part.function_call.args:
                            try:
                                # Execute the function with its arguments
                                output = function(**part.function_call.args)

                                # Add successful response
                                content.parts.append(  # type: ignore
                                    types.Part(
                                        function_response=types.FunctionResponse(
                                            id=part.function_call.id,
                                            name=function_name,
                                            response={"output": output},
                                        )
                                    )
                                )
                            except Exception as e:
                                # Add error response
                                error_msg = f"Error executing {function_name}: {str(e)}"
                                content.parts.append(  # type: ignore
                                    types.Part(
                                        function_response=types.FunctionResponse(
                                            id=part.function_call.id,
                                            name=function_name,
                                            response={"error": error_msg},
                                        )
                                    )
                                )
                                print(error_msg)
                        else:
                            # Handle unknown or invalid function
                            error_msg = f"Unknown or invalid function: {function_name}"
                            content.parts.append(  # type: ignore
                                types.Part(
                                    function_response=types.FunctionResponse(
                                        id=part.function_call.id,
                                        name=function_name or "unknown_function",
                                        response={"error": error_msg},
                                    )
                                )
                            )
                            print(error_msg)

                    # Handle text responses
                    if part.text:
                        execution_occurred = True

                # Update chat with response and function execution results
                chat = chat_history.for_summarizer()
                chat.append(response.candidates[0].content)  # type: ignore
                chat.append(content)  # type: ignore

                # If no execution occurred, we're done
                if not execution_occurred:
                    break

            # Successfully completed
            return True

        except Exception as e:
            # Handle retry logic
            error_msg = f"Attempt {attempt + 1} failed: {str(e)}"
            print(error_msg)

            if attempt < config.MAX_RETRIES - 1:
                # Calculate backoff time
                backoff_time = (2 ** attempt) * config.RETRY_DELAY
                print(f"Waiting {backoff_time:.2f} seconds before next attempt...")
                time.sleep(backoff_time)
            else:
                print(f"Max retries ({config.MAX_RETRIES}) reached. Failed to reduce token usage.")
                return False

    # This line should not be reached if the retry logic is working correctly
    return False

# ID & [its chuncks with their idx & is fully uploded (true if video is fully uploded otherwise false)]
files: dict[str, tuple[dict[int, str], bool]] = {}

@socketio.on("start_upload_file")
def start_upload_file(id: str):
    files[id] = ({}, False)

@socketio.on("upload_file_chunck")
def upload_file_chunck(data: dict[str, str | int]):
    id: str = data["id"]  # type: ignore
    chunck: str = data["chunck"]  # type: ignore
    idx: int = data["idx"]  # type: ignore
    files[id][0][idx] = chunck

@socketio.on("end_upload_file")
def end_upload_file(id: str):
    files[id] = (files[id][0], True)

#region Notification Handling
@socketio.on("get_notifications")
def handle_get_notifications():
    socketio.emit("notification_update", [notification.jsonify() for notification in notification.notifications.notifications])

@socketio.on("mark_read")
def handle_mark_read(data):
    notification_id = data.get("notification_id")
    if notification_id:
        notification.notifications.delete(notification_id)
        socketio.emit("delete_notification", notification_id)
        notification.notifications.save_to_json(os.path.join(config.AI_DIR, "notifications.json")) # Save the updated notifications
    else:
        print("Error: notification_id not provided for mark_read")
#endregion

@socketio.on("send_message")
def handle_send_message(data):
    message = data.get("message", "")
    file_attachments = []
    file_data_list = data.get("files", [])

    for file_data in file_data_list:
        file_type: str = file_data.get("type")
        filename: str = file_data.get("filename")

        id: str = file_data.get("id")
        while (not files.get(id)):
            time.sleep(0.1)
        while (not files[id][1]):
            time.sleep(0.2)
        vid = files[id][0]
        x = 0
        content: str = ""
        while (vid.get(x) is not None):
            content += vid[x]
            x += 1
        decoded_content = base64.b64decode(content)
        file_attachments.append(File(
            decoded_content, file_type, filename, None, File._generate_valid_video_file_id()))
        del files[id]

    complete_chat(message, file_attachments)

@socketio.on("retry_msg")
def handle_retry_message(msg_id: str):
    """
    Handles the retry message event.
    Removes any message after the user message and generates the content.
    """
    try:
        chat_history.tripAfter(msg_id)
        ai_response = get_ai_response()
        if ai_response:
            update_chat_message(ai_response)
    except ValueError as e:
        print(f"Error retrying message: {e}")

@app.route("/get_models")
def get_models() -> list[str]:
    return config.ModelsSet

@socketio.on("set_models")
def set_models(lmodel: Optional[str] = None):
    global model
    model = lmodel

@socketio.on("set_tools")
def set_tools(ltools: Optional[list[tools.ToolLiteral]] = None) -> None:
    global selected_tools
    selected_tools = ltools

@app.route("/get_tools")
def get_tools() -> list[tools.ToolLiteral]:
    return tools.Tools.tool_names()

@app.route("/get_model_compatibility")
def get_model_compatibility() -> dict:
    return {
        "toolSupportedModels": config.ToolSuportedModels,
        "searchGroundingSupportedModels": config.SearchGroundingSuportedModels
    }

@socketio.on("get_chat_history")
def handle_get_chat_history():
    socketio.emit("chat_update", chat_history.jsonify())

@socketio.on("delete_message")
def handle_delete_message(data):
    msg_id = data.get("message_id")
    chat_history.delete_message(msg_id)

#endregion

#region Flask Routes

@app.route('/favicon.ico')
def favicon():
    return redirect(url_for('static', filename='favicon.ico'), code=302)

@app.route('/')
def root():
    return render_template('index.html')

#endregion

if __name__ == "__main__":
    chat_history_file = os.path.join(config.AI_DIR, "chat_history.json")
    chat_history.load_from_json(chat_history_file)
    notification_file = os.path.join(config.AI_DIR, "notifications.json")
    notification.notifications.load_from_json(notification_file)
    mail_checker = threading.Thread(target=start_checking_mail, daemon=True)
    mail_checker.start()
    try:
        reminder_runer = threading.Thread(target=tools.run_reminders, daemon=True)
        reminder_runer.start()
        socketio.run(app, host='127.0.0.1', port=5000,
                     debug=True, use_reloader=False)
    finally:
        chat_history.save_to_json(chat_history_file)
        notification.notifications.save_to_json(notification_file)
        tools.save_jobs()
        print("Chat history saved.")
