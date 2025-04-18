# main.py
import faulthandler
faulthandler.enable()
import re
import traceback
from rich import print
from flask import Flask, render_template, redirect, url_for
from flask_socketio import SocketIO
from google import genai
from google.genai import types
import prompt
import config
import uuid
from io import BytesIO
from typing import Any, Literal, Optional, TypedDict, NamedTuple, cast
from mail import start_checking_mail
from global_shares import global_shares
import notification
import lschedule
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
global_shares["client"] = client

model: Optional[str] = None  # None for Auto
selected_tools: Optional[list[tools.ToolLiteral]] = None  # None for Auto

permission: Optional[bool] = None


@socketio.on("set_permission")
def set_permission(val: bool):
    global permission
    permission = val


def take_permission(msg: str) -> bool:
    socketio.emit("take_permission", msg)
    global permission
    while permission is None:
        time.sleep(0.1)
    perm = permission
    permission = None
    return perm


global_shares["take_permision"] = take_permission


class File:
    type: str = ""  # mime types
    content: bytes = b""
    filename: str = ""
    id: str = ""
    cloud_uri: Optional[types.File] = None  # None if not uploded yet

    def __init__(
        self,
        content: bytes,
        type: str,
        filename: str,
        cloud_uri: Optional[types.File] = None,
        id: Optional[str] = None,
    ):
        self.content = content
        self.type = type
        self.filename = filename
        self.id = str(uuid.uuid4()) if id is None else id
        self.cloud_uri = cloud_uri

    def delete(self):
        if (
            self.cloud_uri
            and self.is_file_valid(self.cloud_uri.expiration_time)
            and self.cloud_uri.name
        ):
            client.files.delete(name=self.cloud_uri.name)

    @staticmethod
    def _generate_valid_file_id():
        """Generates a valid ID that conforms to the naming requirements."""
        base_id = str(uuid.uuid4()).lower()[:35]
        valid_id = re.sub(r"^[^a-z0-9]+|[^a-z0-9]+$", "", base_id)
        return valid_id

    @staticmethod
    def is_file_valid(expiration_time: datetime.datetime | None) -> bool:
        if expiration_time is None:
            return True
        now = datetime.datetime.now(datetime.timezone.utc)
        ten_minutes_from_now = now + datetime.timedelta(minutes=10)  # 10 min buffer

        return expiration_time >= ten_minutes_from_now

    @utils.retry(
        exceptions=utils.network_errors + (ValueError,),
        ignore_exceptions=utils.ignore_network_error,
    )
    def upload_file(self):
        self.cloud_uri = client.files.upload(
            file=BytesIO(self.content),
            config=types.UploadFileConfig(
                display_name=self.filename, mime_type=self.type
            ),
        )
        while self.cloud_uri.state == types.FileState.PROCESSING:
            time.sleep(0.3)
            if self.cloud_uri.name:
                self.cloud_uri = client.files.get(name=self.cloud_uri.name)
            else:
                raise ValueError("Failed to Upload File")
        if self.cloud_uri.state == types.FileState.FAILED:
            raise ValueError(self.cloud_uri.state.name)

    def for_ai(
        self, imagen_selected: bool, msg: Optional["Message"] = None
    ) -> types.Part | tuple[types.Part, types.Part]:
        """
        Prepares the file for use with the AI model.

        Args:
            imagen_selected (bool): Indicates if the image generation tool is selected.
            msg (Optional["Message"]): The message object, used for updating the UI during file processing.

        Returns:
            types.Part | tuple[types.Part, types.Part]: The file as a Part object, ready for AI processing.
                                                        Returns a tuple of Parts if imagen_selected is True and the file is an image.

        Raises:
            ValueError: If the file type is not supported.
            Exception: If file upload fails or file URI/MIME type are not available.
        """
        # Check if the file type is supported
        if (
            self.type.startswith(("text/", "image/", "video/"))
            or self.type == "application/pdf"
        ):
            # Check if the file needs to be uploaded to the cloud
            if not self.cloud_uri or not self.is_file_valid(
                self.cloud_uri.expiration_time
            ):
                # Determine the processing prefix based on the file type
                if self.type.startswith("image/"):
                    prefix = "Processing Image:"
                elif self.type.startswith("text/"):
                    prefix = "Processing Text File:"
                elif self.type.startswith("video/"):
                    prefix = "Processing Video:"
                else:
                    prefix = "Processing PDF:"

                # Update the UI to indicate that the file is being processed
                if msg:
                    msg.content.append(Content(text=f"{prefix} {self.filename}"))
                    emit_msg_update(msg)

                # Upload the file to the cloud
                self.upload_file()

                # Remove the processing message from the UI
                if msg:
                    msg.content.pop()
                    emit_msg_update(msg)

            # Check if the file was successfully uploaded or not
            if not self.cloud_uri:
                raise Exception("Failed to upload type")
            if not self.cloud_uri.uri or not self.cloud_uri.mime_type:
                raise Exception("file uri & mime type not available")

            # Prepare the file part for the AI model
            if imagen_selected and self.type.startswith("image/"):
                # If the image generation tool is selected and the file is an image, attach image id with image for the AI to also give access of the image to the Imageine tool
                return (
                    types.Part(text=f"Image ID: {self.id}"),
                    types.Part.from_uri(
                        file_uri=self.cloud_uri.uri, mime_type=self.cloud_uri.mime_type
                    ),
                )
            return types.Part.from_uri(
                file_uri=self.cloud_uri.uri, mime_type=self.cloud_uri.mime_type
            )
        raise ValueError(f"Unsported File Type: {self.type} of file {self.filename}")

    def jsonify(self) -> dict:
        return {
            "type": self.type,
            "filename": self.filename,
            "content": base64.b64encode(self.content).decode("utf-8", errors="ignore"),
            "id": self.id,
            "cloud_uri": self.cloud_uri.to_json_dict() if self.cloud_uri else None,
        }

    @staticmethod
    def from_jsonify(data: dict):
        content = base64.b64decode(data["content"])
        return File(
            content=content,
            type=data["type"],
            filename=data["filename"],
            cloud_uri=(
                types.File.model_validate(data["cloud_uri"])
                if data["cloud_uri"]
                else None
            ),
            id=data["id"],
        )


global_shares["file"] = File


class Segment(TypedDict):
    start_index: int
    end_index: int
    text: str


class GroundingSupport:
    grounding_chunk_indices: list[int]
    segment: Segment

    def __init__(
        self,
        grounding_chunk_indices: list[int],
        segment: Segment,
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
        return GroundingSupport(**data)


class GroundingChunck(NamedTuple):
    title: str
    uri: str


class GroundingMetaData:
    grounding_chuncks: list[GroundingChunck]
    grounding_supports: list[GroundingSupport]
    first_offset: int
    rendered_content: str

    def __init__(
        self,
        grounding_chuncks: Optional[list[GroundingChunck]] = None,
        grounding_supports: Optional[list[GroundingSupport]] = None,
        first_offset: int = 0,
        rendered_content: str = "",
    ):
        self.grounding_chuncks = grounding_chuncks if grounding_chuncks else []
        self.grounding_supports = grounding_supports if grounding_supports else []
        self.first_offset = first_offset
        self.rendered_content = rendered_content

    def jsonify(self) -> dict[str, Any]:
        return {
            "grounding_chuncks": self.grounding_chuncks,
            "grounding_supports": [gsp.jsonify() for gsp in self.grounding_supports],
            "first_offset": self.first_offset,
            "rendered_content": self.rendered_content,
        }

    @staticmethod
    def from_jsonify(data: dict):
        return GroundingMetaData(
            grounding_chuncks=data["grounding_chuncks"],
            grounding_supports=[
                GroundingSupport.from_jsonify(sup) for sup in data["grounding_supports"]
            ],
            first_offset=data["first_offset"],
            rendered_content=data["rendered_content"],
        )


class FunctionCall:
    id: str
    name: Optional[str]
    args: dict[str, Any]
    extra_data: dict[str, Any]

    def __init__(
        self,
        id: Optional[str] = None,
        name: Optional[str] = None,
        args: Optional[dict[str, Any]] = None,
        extra_data: Optional[dict[str, Any]] = None,
    ):
        self.id = id if id else str(uuid.uuid4())
        self.name = name
        self.args = args if args else {}
        self.extra_data = extra_data if extra_data else {}

    def for_ai(self) -> types.Part:
        return types.Part(
            function_call=types.FunctionCall(id=self.id, name=self.name, args=self.args)
        )

    def jsonify(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "args": self.args,
            "extra_data": self.extra_data,
        }

    @staticmethod
    def from_jsonify(data: dict[str, Any]) -> "FunctionCall":
        return FunctionCall(**data)


class FunctionResponce:
    id: str
    name: Optional[str]
    response: dict[str, Any]
    inline_data: list["Content"]

    def __init__(
        self,
        id: Optional[str] = None,
        name: Optional[str] = None,
        response: Optional[dict[str, Any]] = None,
        inline_data: Optional[list["Content"]] = None,
    ):
        self.id = id if id else str(uuid.uuid4())
        self.name = name
        self.response = response if response else {}
        self.inline_data = inline_data if inline_data else []

    def for_ai(
        self, suport_tools: bool, imagen_selected: bool, msg: Optional["Message"] = None
    ) -> list[types.Part]:
        parts = [
            types.Part(
                function_response=types.FunctionResponse(
                    id=self.id, name=self.name, response=self.response
                )
            )
        ]
        for content in self.inline_data:
            if content.text:
                parts.append(
                    cast(types.Part, content.for_ai(suport_tools, imagen_selected, msg))
                )
            elif content.attachment:
                fai = content.attachment.for_ai(imagen_selected, msg)
                if isinstance(fai, types.Part):
                    parts.append(fai)
                else:
                    parts.extend(fai)
        return parts

    def jsonify(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "response": self.response,
            "inline_data": [_.jsonify() for _ in self.inline_data],
        }

    @staticmethod
    def from_jsonify(data: dict[str, Any]) -> "FunctionResponce":
        return FunctionResponce(
            data["id"],
            data["name"],
            data["response"],
            [Content.from_jsonify(_) for _ in data["inline_data"]],
        )


class Content:
    text: Optional[str] = None
    attachment: Optional[File] = None
    grounding_metadata: Optional[GroundingMetaData] = None
    function_call: Optional[FunctionCall] = None
    function_response: Optional[FunctionResponce] = None

    def __init__(
        self,
        text: Optional[str] = None,
        attachment: Optional[File] = None,
        grounding_metadata: Optional[GroundingMetaData] = None,
        function_call: Optional[FunctionCall] = None,
        function_response: Optional[FunctionResponce] = None,
    ):
        self.text = text
        self.attachment = attachment
        self.grounding_metadata = grounding_metadata
        self.function_call = function_call
        self.function_response = function_response

    def for_ai(
        self, suport_tools: bool, imagen_selected: bool, msg: Optional["Message"] = None
    ) -> types.Part | tuple[types.Part, types.Part] | list[types.Part] | None:
        if self.function_call and suport_tools:
            return self.function_call.for_ai()
        elif self.function_response and suport_tools:
            return self.function_response.for_ai(suport_tools, imagen_selected, msg)
        elif self.text:
            return types.Part(text=self.text)
        elif self.attachment:
            return self.attachment.for_ai(imagen_selected, msg)
        return None

    def jsonify(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "attachment": self.attachment.jsonify() if self.attachment else None,
            "grounding_metadata": (
                self.grounding_metadata.jsonify() if self.grounding_metadata else None
            ),
            "function_call": (
                self.function_call.jsonify() if self.function_call else None
            ),
            "function_response": (
                self.function_response.jsonify() if self.function_response else None
            ),
        }

    @staticmethod
    def from_jsonify(data: dict[str, Any]) -> "Content":
        return Content(
            text=data["text"],
            attachment=File.from_jsonify(data["attachment"]) if data["attachment"] else None,
            grounding_metadata=GroundingMetaData.from_jsonify(data["grounding_metadata"]) if data["grounding_metadata"] else None,
            function_call=(
                FunctionCall.from_jsonify(data["function_call"])
                if data["function_call"]
                else None
            ),
            function_response=(
                FunctionResponce.from_jsonify(data["function_response"])
                if data["function_response"]
                else None
            ),
        )


global_shares["content"] = Content


class Chat:
    name: str
    id: str
    parent_id: Optional[str]

    def __init__(
        self, name: str, id: Optional[str] = None, parent_id: Optional[str] = None
    ):
        self.name = name
        self.id = id if id else str(uuid.uuid4())
        self.parent_id = parent_id

    def jsonify(self) -> dict[str, Any]:
        return {"name": self.name, "id": self.id, "parent_id": self.parent_id}

    @staticmethod
    def from_json(data: dict[str, Any]) -> "Chat":
        return Chat(**data)


class Message:
    role: Literal["model", "user"]
    content: list[Content]
    thought: str
    time_stamp: datetime.datetime
    id: str
    processing: bool
    chat_id: str

    def __init__(
        self,
        content: list[Content],
        role: Literal["model", "user"],
        chat_id: str,
        time_stamp: Optional[datetime.datetime] = None,
        id: Optional[str] = None,
        thought: str = "",
        processing: bool = False,
    ):
        self.time_stamp = time_stamp if time_stamp else datetime.datetime.now()
        self.content = content
        self.role = role
        self.id = str(uuid.uuid4()) if id is None else id
        self.thought = thought
        self.processing = processing
        self.chat_id = chat_id

    def is_member(self, chat: Chat, chats: dict[str, Chat]) -> bool:
        if self.chat_id == chat.id:
            return True
        for child in chats.values():
            if child.parent_id == chat.id and self.is_member(child, chats):
                return True
        return False

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
        raise ValueError(
            f"Function Call with ID `{ID}` not found in message `{self.id}`."
        )

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
        raise ValueError(
            f"Function Responce with ID `{ID}` not found in message `{self.id}`."
        )

    def delete_func_responce(self, ID: str):
        for idx, item in enumerate(self.content):
            if item.function_response:
                if item.function_response.id == ID:
                    del self.content[idx]
                    return

    def for_ai(
        self, suport_tools: bool, imagen_selected: bool, msg: Optional["Message"] = None
    ) -> list[types.Content]:
        if msg is None:
            raise ValueError("msg parameter is required.")

        ai_contents: list[types.Content] = []
        parts_buffer = []

        for item in self.content:
            if item.function_response and suport_tools:
                if parts_buffer:
                    ai_contents.append(
                        types.Content(parts=parts_buffer, role=self.role)
                    )
                    parts_buffer = []
                if part := item.function_response.for_ai(
                    suport_tools, imagen_selected, msg
                ):
                    ai_contents.append(types.Content(parts=part, role="user"))
            elif part := item.for_ai(suport_tools, imagen_selected, msg):
                if isinstance(part, types.Part):
                    parts_buffer.append(part)
                elif isinstance(part, tuple):
                    parts_buffer.extend(part)
                # list not posible cz it is oly when `function_response`

        if parts_buffer:
            ai_contents.append(types.Content(parts=parts_buffer, role=self.role))
        return ai_contents

    def jsonify(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "content": [item.jsonify() for item in self.content],
            "id": self.id,
            "chat_id": self.chat_id,
            "time_stamp": self.time_stamp.isoformat(),
            "thought": self.thought,
            "processing": self.processing,
        }

    @staticmethod
    def from_jsonify(data: dict):
        return Message(
            content=[Content.from_jsonify(item) for item in data["content"]],
            role=data["role"],
            chat_id=data["chat_id"],
            time_stamp=datetime.datetime.fromisoformat(data["time_stamp"]),
            id=data["id"],
            thought=data["thought"],
        )


class ChatHistory:
    _messages: list[Message] = []
    _chats: dict[str, Chat] = {"main": Chat("Main Chat", "main")}

    def add_chat(self, chat: Chat):
        """Adds a new chat definition."""
        if chat.id in self._chats:
            print(f"Warning: Chat with ID {chat.id} already exists. Overwriting.")
        if chat.parent_id and chat.parent_id not in self._chats:
            raise ValueError(f"Parent chat with ID {chat.parent_id} does not exist.")
        self._chats[chat.id] = chat

    def get_chat(self, chat_id: str) -> Chat:
        """Gets chat metadata."""
        if chat_id not in self._chats:
            raise ValueError(f"Chat with ID {chat_id} not found.")
        return self._chats[chat_id]

    def append(self, msg: Message):
        self._messages.append(msg)
        socketio.emit("add_message", msg.jsonify())

    def delete_message(self, msg_id):
        self._messages = [msg for msg in self._messages if msg.id != msg_id]
        emit_msg_del(msg_id)

    def __len__(self):
        return len(self._messages)

    def __getitem__(self, idx: int):
        return self._messages[idx]

    def getImage(self, ID: str) -> tuple[types.Part, types.Part] | types.Part:
        for msg in self._messages:
            for content in msg.content:
                if content.attachment and content.attachment.id == ID:
                    return content.attachment.for_ai(True)
                elif (
                    content.function_response and content.function_response.inline_data
                ):
                    for content in content.function_response.inline_data:
                        if content.attachment and content.attachment.id == ID:
                            return content.attachment.for_ai(True)
        raise ValueError(f"Image with ID: `{ID}` not found")

    def getMsg(self, ID: str) -> Message:
        for msg in self._messages:
            if msg.id == ID:
                return msg
        raise ValueError(f"Message of ID: `{ID}` not found")

    def setMsg(self, ID: str, new_msg: Message):
        for msg in self._messages:
            if msg.id == ID:
                msg = new_msg
                emit_msg_update(msg)
                return
        raise ValueError(f"Message of ID: `{ID}` not found")

    def trip_after(self, msg_id: str, chat_id: str) -> None:
        chat = self._chats[chat_id]
        msg_index = {msg.id: i for i, msg in enumerate(self._messages)}
        idx = msg_index.get(msg_id, -1)
        if idx == -1:
            return  # Message not found, exit early
        ids_to_del = {
            msg.id
            for msg in self._messages[idx + 1 :]
            if msg.is_member(chat, self._chats)
        }
        for msg_id in ids_to_del:
            emit_msg_del(msg_id)
        self._messages = list(
            filter(lambda msg: msg.id not in ids_to_del, self._messages)
        )

    def for_ai(
        self, ai_msg: Message, suport_tools: bool, imagen_selected: bool, chat_id: str
    ) -> list[types.Content]:
        result: list[types.Content] = []
        for msg in self._messages:
            if msg.is_member(self._chats[chat_id], self._chats):
                result.extend(msg.for_ai(suport_tools, imagen_selected, ai_msg))
        return result

    def jsonify(self):
        data = [msg.jsonify() for msg in self._messages]
        return {"messages": data, "chats": [_.jsonify() for _ in self._chats.values()]}

    def save_to_json(self, filepath: str):
        """Saves the chat history to a JSON file."""
        with open(filepath, "w") as f:
            json.dump(self.jsonify(), f, indent=4)

    def load_from_json(self, filepath: str):
        """Loads the chat history from a JSON file."""
        try:
            with open(filepath, "r") as f:
                data = json.load(f)
                self._messages = []
                for msg_data in data.get("messages", ()):
                    msg = Message.from_jsonify(msg_data)
                    self._messages.append(msg)
                for chat in data.get("chats", ()):
                    self._chats[chat["id"]] = Chat.from_json(chat)
                if "main" not in self._chats.keys():
                    print(
                        "Creating default 'main' chat as it was not found in the loaded data."
                    )
                    self._chats["main"] = Chat(name="Main Chat", id="main")
        except FileNotFoundError:
            print("Chat history file not found. Starting with an empty chat.")
        except json.JSONDecodeError:
            print("Error decoding chat history. Starting with an empty chat.")

    def _is_descendant(self, potential_child_id: str, potential_parent_id: str) -> bool:
        """Checks if potential_child_id is a descendant of potential_parent_id."""
        if not potential_parent_id or potential_child_id == potential_parent_id:
            return False  # Cannot be a descendant of null or itself

        current_id = potential_child_id
        while current_id:
            chat = self._chats.get(current_id)
            if not chat:
                return False  # Should not happen if data is consistent
            if chat.parent_id == potential_parent_id:
                return True  # Found the potential parent in the ancestry
            current_id = chat.parent_id  # Move up the chain
        return False  # Reached the root without finding the parent

    def update_chat_parent(self, chat_id: str, new_parent_id: Optional[str]) -> bool:
        """Updates the parent of a chat, preventing circular dependencies."""
        if chat_id == "main":
            print("Error: Cannot change the parent of the 'main' chat.")
            return False  # Prevent moving the main chat

        if chat_id not in self._chats:
            print(f"Error: Chat with ID {chat_id} not found for parent update.")
            return False

        if new_parent_id and new_parent_id not in self._chats:
            print(f"Error: New parent chat with ID {new_parent_id} not found.")
            return False

        if new_parent_id and self._is_descendant(new_parent_id, chat_id):
            print(
                f"Error: Cannot move chat '{chat_id}' under its descendant '{new_parent_id}'."
            )
            return False
        # Also check if trying to move to itself
        if chat_id == new_parent_id:
            print(f"Error: Cannot move chat '{chat_id}' under itself.")
            return False

        # Update the parent ID
        chat_to_update = self._chats[chat_id]
        old_parent_id = chat_to_update.parent_id
        chat_to_update.parent_id = new_parent_id
        print(
            f"Updated parent of chat '{chat_id}' from '{old_parent_id}' to '{new_parent_id}'"
        )
        return True

    def delete_chat(self, chat_id_to_delete: str):
        """Deletes a chat and reparents its children."""
        if chat_id_to_delete == "main":
            raise Exception("Error: Cannot delete the 'main' chat.")

        if chat_id_to_delete not in self._chats:
            raise Exception(
                f"Error: Chat with ID {chat_id_to_delete} not found for deletion."
            )

        messages_to_del = []

        for idx, msg in enumerate(self._messages):
            if msg.is_member(self._chats[chat_id_to_delete], self._chats):
                messages_to_del.append(msg)

        for msg in messages_to_del:
            self._messages.remove(msg)

        # Iterate over a copy of keys because we might modify the dict size implicitly if we delete the chat first
        for chat_id in list(self._chats.keys()):
            # Check if the chat exists (might have been deleted in a recursive call if we change strategy later)
            chat = self._chats.get(chat_id)
            if chat and chat.parent_id == chat_id_to_delete:
                self.delete_chat(chat.id)
                break

        # Delete the chat
        del self._chats[chat_id_to_delete]


chat_history: ChatHistory = ChatHistory()

global_shares["chat_history"] = chat_history


def complete_chat(message: str, chat_id: str, files: Optional[list[File]] = None):
    """
    Appends user message to chat history, gets AI response, and handles grounding metadata.
    """
    # Append user message if there's content
    if message or files:
        append_user_message(message, chat_id, files or [])

    # Get AI response and update chat history
    ai_response = get_ai_response(chat_id)
    emit_msg_update(ai_response)


def append_user_message(message: str, chat_id: str, files: list[File]):
    """Appends the user's message and files to the chat history."""
    chat_history.append(
        Message(
            [*(Content(attachment=file) for file in files), Content(message)],
            "user",
            chat_id,
            datetime.datetime.now(),
        )
    )


def get_ai_response(chat_id: str) -> Message:
    """
    Gets the AI's response from the Gemini model, handling retries and token limits.
    """
    # Append a placeholder for the AI reply
    chat_history.append(Message([], "model", chat_id))
    msg = chat_history[len(chat_history) - 1]
    try:
        return generate_content(msg, chat_id)
    except Exception as e:
        handle_generation_failure(msg, e)
        return msg


def emit_msg_update(msg: Message):
    """
    emits the updated message.
    """
    socketio.emit("updated_msg", msg.jsonify())


def emit_msg_del(msg_id: str):
    """
    emits the delete message.
    """
    socketio.emit("delete_message", msg_id)


def generate_content(msg: Message, chat_id: str) -> Message:
    """
    Generates content from Gemini, retrying on token limits or other errors.

    Args:
        msg: Message object to be populated with generated content

    Returns:
        Populated Message object with generated content
    """

    # Helper function to handle streaming content parts
    def handle_part(part: types.Part):
        # Handle thought content
        if part.thought and part.text:
            msg.thought += part.text

        # Handle regular text content
        elif part.text:
            # Create initial content if none exists
            if not msg.content:
                msg.content.append(Content(text=""))

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
        msg.content.append(
            Content(
                function_call=FunctionCall(
                    id=func_call.id, name=func_call.name, args=func_call.args
                )
            )
        )
        fc: FunctionCall = msg.content[-1].function_call  # type: ignore
        id: str = msg.content[-1].function_call.id  # type: ignore
        emit_msg_update(msg)

        try:
            # Validate function name
            if not func_call.name:
                raise ValueError("Function with no name specified")
            if func_call.name == "DeepResearch":
                if func_call.args:
                    def research_callback(update_data: Optional[dict[str, Any]]) -> None:
                        # print(update_data)
                        if not update_data:
                            # No specific update, maybe just a state check internally
                            return

                        # Prepare data for the frontend event
                        event_payload = {
                            "function_id": id, # Pass the function call ID
                            "update_type": update_data.get("action"),
                            "data": update_data # Send the original data payload
                        }
                        # Map actions to update types if needed, or use action directly
                        if update_data.get("action") == "thinking":
                            event_payload["update_type"] = "step" # More specific type
                            event_payload["data"] = {"type": "thinking", "content": update_data.get("thoughts")}
                            fc.extra_data["steps"].append(event_payload["data"])
                        elif update_data.get("action") == "topic_updated":
                            event_payload["update_type"] = "topic_tree"
                            event_payload["data"] = researcher.topic.jsonify()
                            fc.extra_data["topic"] = event_payload["data"]
                        elif update_data.get("action") == "search":
                            event_payload["update_type"] = "step" # More specific type
                            event_payload["data"] = update_data
                            fc.extra_data["steps"].append(update_data)
                        elif update_data.get("action") == "update_search":
                            event_payload["update_type"] = "step" # More specific type
                            event_payload["data"] = update_data.copy()
                            idx = None
                            for idx, step in enumerate(fc.extra_data["steps"]):
                                if step.get("type") == "search" and step["id"] == update_data["id"]:
                                    break
                            fc.extra_data["steps"][idx] = update_data
                        elif update_data.get("action") == "generating_report":
                            event_payload["update_type"] = "step"
                            event_payload["data"] = {"type": "report_gen"}
                            fc.extra_data["steps"].append(event_payload["data"])
                        elif update_data.get("action") == "done_generating_report":
                            event_payload["update_type"] = "done_generating_report"
                            event_payload["data"] = {"type": "done_generating_report", "report": update_data["data"]}
                            fc.extra_data["steps"].pop()
                            fc.extra_data["steps"].append(event_payload["data"])
                        elif update_data.get("action") == "summarize_sites":
                            event_payload["update_type"] = "step"
                            event_payload["data"] = {"type": "summarize_sites", "topic": update_data.get("topic")}
                            fc.extra_data["steps"].append(event_payload["data"])
                            print(event_payload["data"])
                        elif update_data.get("action") == "summarize_sites_complete":
                            event_payload["update_type"] = "step"
                            event_payload["data"] = {"type": "summarize_sites_complete", "topic": update_data.get("topic")}
                            print(event_payload["data"])
                            # Find and remove the summarize_sites step
                            for idx, step in enumerate(fc.extra_data["steps"]):
                                if step.get("type") == "summarize_sites" and step.get("topic") == update_data.get("topic"):
                                    del fc.extra_data["steps"][idx]
                                    break

                        socketio.emit('research_update', event_payload)
                        emit_msg_update(msg) # cz fc is updated but the content in the message is not get to the website

                    researcher = tools.DeepResearcher(
                        **func_call.args, call_back=research_callback # Use the new callback
                    )
                    # Store initial state in extra_data (no change here)
                    fc.extra_data["topic"] = researcher.topic.jsonify()
                    fc.extra_data["steps"] = [] # Steps will be added via events
                    fc.extra_data["max_topics"] = researcher.max_topics
                    fc.extra_data["max_search_queries"] = researcher.max_search_queries
                    fc.extra_data["max_search_results"] = researcher.max_search_results
                    fc.extra_data["stop"] = False
                    fc.extra_data["status"] = "running" # Add initial status

                    # --- Modify Config Update Handlers ---
                    def update_max_topics(max_topics: Optional[int]):
                        researcher.max_topics = max_topics
                        fc.extra_data["max_topics"] = max_topics
                        # Emit config update event
                        socketio.emit('research_update', {
                            "function_id": id,
                            "update_type": "config",
                            "data": {"max_topics": max_topics}
                        })

                    def update_max_search_queries(max_search_queries: Optional[int]):
                        researcher.max_search_queries = max_search_queries
                        fc.extra_data["max_search_queries"] = max_search_queries
                        socketio.emit('research_update', {
                            "function_id": id,
                            "update_type": "config",
                            "data": {"max_search_queries": max_search_queries}
                        })

                    def update_max_search_results(max_search_results: Optional[int]):
                        researcher.max_search_results = max_search_results
                        fc.extra_data["max_search_results"] = max_search_results
                        socketio.emit('research_update', {
                            "function_id": id,
                            "update_type": "config",
                            "data": {"max_search_results": max_search_results}
                        })

                    def stop_research():
                        researcher.stop = True
                        fc.extra_data["stop"] = True
                        fc.extra_data["status"] = "stopping"
                        socketio.emit('research_update', {
                            "function_id": id,
                            "update_type": "status",
                            "data": {"stopped": True, "status": "stopping"}
                        })

                    # Store handlers for later removal (no change here)
                    registered_events = {}
                    def make_event(event_name, handler_func):
                        # Use unique event names per research instance
                        full_event_name = f"{event_name}_{id}"
                        socketio.on(full_event_name)(handler_func)
                        registered_events[full_event_name] = handler_func # Store the full name

                    make_event("research-update_max_topics", update_max_topics)
                    make_event("research-update_max_queries", update_max_search_queries)
                    make_event("research-update_max_results", update_max_search_results)
                    make_event("research-stop", stop_research)

                    # --- Run Research and Handle Completion/Error ---
                    # Emit initial state update (optional, but good practice)
                    socketio.emit('research_update', {
                        "function_id": id,
                        "update_type": "initial_state",
                        "data": fc.extra_data
                    })
                    # Emit the initial message update *once* to show the call box
                    emit_msg_update(msg)
                    try:
                        response_payload = {"output": researcher.research()}
                    except Exception:
                        response_payload = {"error": traceback.format_exc()}
                    fc.extra_data["status"] = "finished"

                    # Add the final response/error to the message *content*
                    msg.content.append(
                        Content(
                            function_response=FunctionResponce(
                                id=id,
                                name=func_call.name,
                                response=response_payload,
                            )
                        )
                    )
                    # Emit the final message update to include the response box
                    emit_msg_update(msg)

                    # Emit a final status update event
                    socketio.emit('research_update', {
                        "function_id": id,
                        "update_type": "status",
                        "data": {"status": fc.extra_data["status"], "stopped": fc.extra_data["stop"]}
                    })
                    # Emit a specific event to signal frontend cleanup is safe
                    socketio.emit('research_finished', {"function_id": id})

                    # Return from handle_function_call (important!)
                    # Since research runs synchronously here, we don't return early.
                    # The final message update happens after research completes.
                    return # Explicitly return after handling

                else:
                    raise ValueError("DeepResearch call without args")
            else:
                # Call the appropriate tool function and add response
                if func_call.args:
                    func_response = getattr(tools, func_call.name)(**func_call.args)
                else:
                    func_response = getattr(tools, func_call.name)()
            if func_call.name == "Imagen":
                msg.content.append(
                    Content(
                        function_response=FunctionResponce(
                            id=id,
                            name=func_call.name,
                            response={"output": "Images are Linked Below"},
                            inline_data=func_response,
                        )
                    )
                )
                return
            elif func_call.name == "LinkAttachment":
                msg.content.append(
                    Content(
                        function_response=FunctionResponce(
                            id=id,
                            name=func_call.name,
                            response={"output": "Files are Linked Below"},
                            inline_data=func_response,
                        )
                    )
                )
                return

            # Add successful function response
            msg.content.append(
                Content(
                    function_response=FunctionResponce(
                        id=id,
                        name=func_call.name,
                        response={"output": func_response},
                    )
                )
            )

        except Exception as e:
            # Add error response with detailed exception info
            error_msg = f"Error executing {func_call.name}: {str(e)}"
            msg.content.append(
                Content(
                    function_response=FunctionResponce(
                        id=id,
                        name=func_call.name or "unknown_function",
                        response={"error": error_msg},
                    )
                )
            )
        emit_msg_update(msg)

    @utils.retry(
        exceptions=utils.network_errors, ignore_exceptions=utils.ignore_network_error
    )
    def get_model_and_tools() -> tuple[str, bool, list[types.Tool]]:
        """
        Determines which model and tools to use, with retry logic.

        Returns:
            Tuple of (model_name, tools_list)

        Raises:
            Exception: If selection fails after multiple attempts
        """
        chat = chat_history.for_ai(msg, True, False, chat_id)
        global model
        allowed_function_names: Optional[list[str]] = None
        # Case 1: Both model and tools are already selected
        if model is not None and selected_tools is not None:
            tols = [
                tools.Tools[selected_tool].value for selected_tool in selected_tools
            ]
            return (
                config.Models[model].value,
                model in config.ToolSuportedModels
                and tools.SearchGrounding not in tols,
                tols,
            )

        # Case 2: Only model is selected, need to select tools
        elif model is not None:
            if model in config.SearchGroundingSuportedModels:
                chat.append(
                    types.Content(
                        parts=[
                            types.Part(
                                text="Select which tools to use to reply to the user message."
                            )
                        ],
                        role="user",
                    )
                )
                tools_list = [
                    types.Tool(
                        function_declarations=[
                            types.FunctionDeclaration.from_callable_with_api_option(
                                callable=tools.ToolSelector
                            )
                        ]
                    )
                ]
                allowed_function_names = [tools.ToolSelector.__name__]
            elif model in config.ToolSuportedModels:
                chat.append(
                    types.Content(
                        parts=[
                            types.Part(
                                text="Select which tools to use to reply to the user message. "
                                "Important: Don't use `Search` tool as it's not supported by the current model."
                            )
                        ],
                        role="user",
                    )
                )
                tools_list = [
                    types.Tool(
                        function_declarations=[
                            types.FunctionDeclaration.from_callable_with_api_option(
                                callable=tools.ToolSelector
                            )
                        ]
                    )
                ]
                allowed_function_names = [tools.ToolSelector.__name__]
            else:
                return config.Models[model].value, True, []

        # Case 3: Only tools are selected, need to select model
        elif selected_tools is not None:
            if tools.Tools.SearchGrounding.name in selected_tools:
                chat.append(
                    types.Content(
                        parts=[
                            types.Part(
                                text=f"Select which model to use to reply to the user message. "
                                f"Important: Use only these models: {config.SearchGroundingSuportedModels} "
                                f"as they are the only ones that support `SearchGrounding`."
                            )
                        ],
                        role="user",
                    )
                )
            else:
                chat.append(
                    types.Content(
                        parts=[
                            types.Part(
                                text=f"Select which model to use to reply to the user message. "
                                f"Important: Use only these models: {config.ToolSuportedModels} "
                                f"as they are the only ones that support Tool Calling."
                            )
                        ],
                        role="user",
                    )
                )
            tools_list = [
                types.Tool(
                    function_declarations=[
                        types.FunctionDeclaration.from_callable_with_api_option(
                            callable=tools.ModelSelector
                        )
                    ]
                )
            ]
            allowed_function_names = [tools.ModelSelector.__name__]

        # Case 4: Neither model nor tools selected, need to select both
        else:
            chat.append(
                types.Content(
                    parts=[
                        types.Part(
                            text="Select which model and tools to use to reply to the user message."
                        )
                    ],
                    role="user",
                )
            )
            tools_list = [
                types.Tool(
                    function_declarations=[
                        types.FunctionDeclaration.from_callable_with_api_option(
                            callable=tools.ModelAndToolSelector
                        )
                    ]
                )
            ]
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
                            disable=True, maximum_remote_calls=None
                        ),
                        tool_config=types.ToolConfig(
                            function_calling_config=types.FunctionCallingConfig(
                                mode=types.FunctionCallingConfigMode.ANY,
                                allowed_function_names=allowed_function_names,
                            )
                        ),
                    ),
                )

                # Process response if function calls are present
                if (
                    selector_response.function_calls
                    and selector_response.function_calls[0].args
                ):
                    call_name = selector_response.function_calls[0].name
                    args = selector_response.function_calls[0].args
                    call_id = selector_response.function_calls[0].id

                    # Handle tool selection when model is known
                    if call_name == "ToolSelector" and model is not None:
                        try:
                            tols = tools.ToolSelector(**args)
                            return (
                                config.Models[model].value,
                                model in config.ToolSuportedModels
                                and tools.SearchGrounding not in tols,
                                tols,
                            )
                        except Exception as e:
                            handle_selector_error(chat, call_id, call_name, e)
                            continue

                    # Handle model selection when tools are known
                    elif call_name == "ModelSelector" and selected_tools is not None:
                        try:
                            tols = tools.ToolSelector(selected_tools)
                            return (
                                tools.ModelSelector(**args),
                                model in config.ToolSuportedModels
                                and tools.SearchGrounding not in tols,
                                tols,
                            )
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
                    chat.append(
                        types.Content(
                            parts=[
                                types.Part(
                                    text="Select which model and tools to use to reply to the user message. "
                                    "You didn't call the required function."
                                )
                            ],
                            role="user",
                        )
                    )
                    continue

            except Exception as e:
                # Log error and continue to next attempt
                print(f"Selection attempt {attempt+1} failed: {str(e)}")
                if attempt == 2:  # Last attempt
                    raise Exception(
                        f"Failed to select model and tools after multiple attempts: {str(e)}"
                    )

        # If we reach here, all attempts failed
        raise Exception(
            "Cannot select models & tools automatically. Please select manually."
        )

    # Helper function to handle selector errors
    def handle_selector_error(chat, call_id, call_name, error):
        error_msg = f"Error occurred while calling function: {error}"
        chat.append(
            types.Content(
                parts=[
                    types.Part(
                        function_response=types.FunctionResponse(
                            id=call_id, name=call_name, response={"error": error_msg}
                        )
                    )
                ],
                role="user",
            )
        )
        print(error_msg)

    # Main execution flow
    msg.processing = True
    emit_msg_update(msg)
    # Get model and tools
    selected_model, suports_tools, selected_tools_list = get_model_and_tools()
    print(f"Using model: {selected_model} with tools: {selected_tools_list}")

    # Main content generation loop
    @utils.retry(
        exceptions=utils.network_errors, ignore_exceptions=utils.ignore_network_error
    )
    def generate_content_with_retry():
        while True:
            start_time = time.time()  # Record start time before request
            # Generate streaming content
            response = client.models.generate_content_stream(
                model=selected_model,
                contents=chat_history.for_ai(msg, suports_tools, tools.ImagenTool in selected_tools_list, chat_id),  # type: ignore
                config=types.GenerateContentConfig(
                    system_instruction=prompt.SYSTEM_INSTUNCTION.format(
                        reminders=(
                            tools.get_reminders() + lschedule.get_todo_list_string()
                            if tools.ReminderTool in selected_tools_list
                            else ""
                        ),
                        dir_tree=(
                            tools.space.CodeExecutionEnvironment.dir_tree()
                            if tools.ComputerTool in selected_tools_list
                            else ""
                        ),
                    ),
                    temperature=config.CHAT_AI_TEMP,
                    tools=selected_tools_list,  # type: ignore
                    automatic_function_calling=types.AutomaticFunctionCallingConfig(
                        disable=True, maximum_remote_calls=None
                    ),
                    # thinking_config=types.ThinkingConfig(include_thoughts=True) # Not suported yet
                ),
            )

            # Process the streaming response
            function_call_occurred = False
            finish_region: types.FinishReason | None = None
            for content in response:
                if (
                    content.candidates
                    and content.candidates[0].content
                    and content.candidates[0].content.parts
                ):

                    for part in content.candidates[0].content.parts:
                        handle_part(part)
                        if part.function_call:
                            function_call_occurred = True
                if content.candidates and content.candidates[0].finish_reason:
                    finish_region = content.candidates[0].finish_reason

                # Process additional metadata
                process_grounding_metadata(msg, content)
                emit_msg_update(msg)

            # sleep for some time if needed
            end_time = time.time()  # Record end time after response processing
            elapsed_time = end_time - start_time  # Calculate elapsed time

            if function_call_occurred or finish_region == types.FinishReason.MAX_TOKENS:
                rpm_limit = config.model_RPM_map.get(
                    selected_model, 1
                )  # Get RPM limit, default to 1 if not found
                target_delay_per_request_sec = (
                    60.0 / rpm_limit
                )  # Calculate target delay in seconds
                sleep_duration = max(
                    0, target_delay_per_request_sec - elapsed_time
                )  # Calculate sleep duration, ensure it's not negative
                if sleep_duration > 0:
                    time.sleep(sleep_duration)  # Sleep to respect RPM limit
                continue

            # Otherwise break the loop
            break

    generate_content_with_retry()

    # Set timestamp and return message
    msg.time_stamp = datetime.datetime.now()
    msg.processing = False
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
            msg.content[-1].grounding_metadata.rendered_content = (
                metadata.search_entry_point.rendered_content or ""
            )

        if metadata.grounding_chunks:
            for chunk in metadata.grounding_chunks:
                if chunk.web:
                    msg.content[-1].grounding_metadata.grounding_chuncks.append(
                        GroundingChunck(
                            chunk.web.title or "unknown", chunk.web.uri or ""
                        )
                    )

        if (
            metadata.grounding_chunks
            and metadata.grounding_supports
            and metadata.web_search_queries
        ):
            process_grounding_supports(msg, metadata)
    emit_msg_update(msg)


def process_grounding_supports(msg: Message, metadata: types.GroundingMetadata):
    """
    Processes grounding support information and updates the message.
    """
    if msg.content[-1].text is None:
        return
    if msg.content[-1].grounding_metadata is None:
        msg.content[-1].grounding_metadata = GroundingMetaData([], [])
    first = True
    for support in metadata.grounding_supports or ():
        if support.segment and support.segment.text and support.grounding_chunk_indices:
            start_index = msg.content[-1].text.find(support.segment.text)
            if start_index == -1:
                escaped_target = re.escape(msg.content[-1].text or "")
                # Create a regex pattern that allows for extra spaces and minor variations
                # Allow any amount of whitespace between chars
                # cz Gemini Grounding Suks
                pattern = r"\s*".join(list(escaped_target))
                match = re.search(pattern, support.segment.text or "")
                if match:
                    return match.start()
                else:
                    continue

            if first:
                msg.content[-1].grounding_metadata.first_offset = start_index - (
                    support.segment.start_index or 0
                )
                first = False

            msg.content[-1].grounding_metadata.grounding_supports.append(
                GroundingSupport(
                    support.grounding_chunk_indices,
                    {
                        "text": support.segment.text,
                        "start_index": start_index,
                        "end_index": start_index + len(support.segment.text),
                    },
                )
            )
    emit_msg_update(msg)


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
    emit_msg_update(msg)


# ID & [its chuncks with their idx & is fully uploded (true if video is fully uploded otherwise false)]
class UploadFileParts(NamedTuple):
    data: dict[int, str]  # data part idx  # b64 data part
    done: bool  # whether file is complitly uploded or not


files: dict[str, UploadFileParts] = {}


@socketio.on("start_upload_file")
def start_upload_file(id: str):
    files[id] = UploadFileParts({}, False)


@socketio.on("upload_file_chunck")
def upload_file_chunck(data: dict):
    id: str = data["id"]
    chunck: str = data["chunck"]
    idx: int = data["idx"]
    files[id].data[idx] = chunck


@socketio.on("end_upload_file")
def end_upload_file(id: str):
    files[id] = UploadFileParts(files[id].data, True)


@socketio.on("get_notifications")
def handle_get_notifications():
    socketio.emit(
        "notification_update",
        [
            notification.jsonify()
            for notification in notification.notifications.notifications
        ],
    )


@socketio.on("mark_read")
def handle_mark_read(data):
    notification_id = data.get("notification_id")
    if notification_id:
        notification.notifications.delete(notification_id)
        socketio.emit("delete_notification", notification_id)
        notification.notifications.save_to_json(
            os.path.join(config.AI_DIR, "notifications.json")
        )  # Save the updated notifications
    else:
        print("Error: notification_id not provided for mark_read")


@socketio.on("send_message")
def handle_send_message(data):
    message = data.get("message", "")
    file_attachments = []
    file_data_list = data.get("files", [])

    for file_data in file_data_list:
        file_type: str = file_data.get("type")
        filename: str = file_data.get("filename")

        id: str = file_data.get("id")
        while not files.get(id):
            time.sleep(0.1)
        while not files[id][1]:
            time.sleep(0.2)
        vid = files[id][0]
        x = 0
        content: str = ""
        while vid.get(x) is not None:
            content += vid[x]
            x += 1
        decoded_content = base64.b64decode(content)
        file_attachments.append(
            File(
                decoded_content,
                file_type,
                filename,
                None,
                File._generate_valid_file_id(),
            )
        )
        del files[id]

    complete_chat(message, data.get("chat_id", "main"), file_attachments)


@socketio.on("retry_msg")
def handle_retry_message(data: dict[str, str]):
    """
    Handles the retry message event.
    Removes any message after the user message and generates the content.
    """
    try:
        chat_history.trip_after(data["msg_id"], data["chat_id"])
        ai_response = get_ai_response(data["chat_id"])
        if ai_response:
            emit_msg_update(ai_response)
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
        "searchGroundingSupportedModels": config.SearchGroundingSuportedModels,
    }


@socketio.on("create_chat")
def handle_create_chat(data):
    """Handles request to create a new chat branch."""
    new_name = data.get("name")
    parent_id = data.get("parent_id")

    if not new_name:
        print("Error: Cannot create chat without a name.")
        return

    if parent_id and parent_id not in chat_history._chats:
        print(f"Error: Cannot create chat. Parent chat ID '{parent_id}' not found.")
        return

    try:
        new_chat = Chat(name=new_name, parent_id=parent_id)
        chat_history.add_chat(new_chat)
        print(
            f"Created new chat: ID={new_chat.id}, Name='{new_name}', Parent={parent_id}"
        )
        socketio.emit("chat_update", chat_history.jsonify())
        chat_history.save_to_json(os.path.join(config.AI_DIR, "chat_history.json"))
    except Exception as e:
        print(f"Error creating chat: {e}")
        traceback.print_exc()


@socketio.on("update_chat_parent")
def handle_update_chat_parent(data):
    """Handles request to update a chat's parent."""
    chat_id = data.get("chat_id")
    new_parent_id = data.get("new_parent_id")  # This can be None/null

    if not chat_id:
        print("Error: chat_id missing in update_chat_parent request.")
        return

    try:
        success = chat_history.update_chat_parent(chat_id, new_parent_id)
        if success:
            chat_history.save_to_json(os.path.join(config.AI_DIR, "chat_history.json"))
            socketio.emit("chat_update", chat_history.jsonify())
    except Exception as e:
        print(f"Error updating chat parent: {e}")
        traceback.print_exc()


@socketio.on("delete_chat")
def handle_delete_chat(data):
    """Handles request to delete a chat."""
    chat_id = data.get("chat_id")

    if not chat_id:
        print("Error: chat_id missing in delete_chat request.")
        return

    if chat_id == "main":
        print("Attempted to delete 'main' chat from client. Denied.")
        return

    try:
        chat_history.delete_chat(chat_id)
        chat_history.save_to_json(os.path.join(config.AI_DIR, "chat_history.json"))
        socketio.emit("chat_update", chat_history.jsonify())
    except Exception as e:
        print(f"Error deleting chat: {e}")
        traceback.print_exc()


@socketio.on("get_chat_history")
def handle_get_chat_history():
    socketio.emit("chat_update", chat_history.jsonify())


@socketio.on("delete_message")
def handle_delete_message(data):
    msg_id = data.get("message_id")
    chat_history.delete_message(msg_id)


@socketio.on("get_schedule")
def handle_get_schedule():
    socketio.emit("schedule_update", lschedule.schedule.jsonify())


@socketio.on("add_task")
def handle_add_task(task_data):
    try:
        task = lschedule.Task.from_dict(task_data)
        lschedule.schedule.add_task(task)
        lschedule.schedule.save_to_json(config.AI_DIR / "schedule.json")
        socketio.emit("schedule_update", lschedule.schedule.jsonify())
    except Exception as e:
        print(f"Error adding task: {e}")
        socketio.emit("schedule_error", str(e))


@socketio.on("update_task")
def handle_update_task(task_data):
    try:
        task = lschedule.Task.from_dict(task_data)
        existing_task = lschedule.schedule.get_task(task.id)
        # Update only the provided fields
        existing_task.title = task.title
        existing_task.start = task.start
        existing_task.end = task.end
        existing_task.allDay = task.allDay
        existing_task.backgroundColor = task.backgroundColor
        existing_task.borderColor = task.borderColor

        lschedule.schedule.update_task(existing_task)
        lschedule.schedule.save_to_json(config.AI_DIR / "schedule.json")
        socketio.emit("schedule_update", lschedule.schedule.jsonify())
    except Exception as e:
        print(f"Error updating task: {e}")
        socketio.emit("schedule_error", str(e))


@socketio.on("complete_task")
def handle_complete_task(task_id):
    try:
        task = lschedule.schedule.get_task(task_id)
        task.completed = True
        lschedule.schedule.update_task(task)
        lschedule.schedule.save_to_json(config.AI_DIR / "schedule.json")
        socketio.emit("schedule_update", lschedule.schedule.jsonify())
    except Exception as e:
        print(f"Error completing task: {e}")
        socketio.emit("schedule_error", str(e))


@socketio.on("reopen_task")
def handle_reopen_task(task_id):
    try:
        task = lschedule.schedule.get_task(task_id)
        task.completed = False
        lschedule.schedule.update_task(task)
        lschedule.schedule.save_to_json(config.AI_DIR / "schedule.json")
        socketio.emit("schedule_update", lschedule.schedule.jsonify())
    except Exception as e:
        print(f"Error reopening task: {e}")
        socketio.emit("schedule_error", str(e))


@socketio.on("delete_task")
def handle_delete_task(task_id):
    try:
        lschedule.schedule.delete_task(task_id)
        lschedule.schedule.save_to_json(config.AI_DIR / "schedule.json")
        socketio.emit("schedule_update", lschedule.schedule.jsonify())
    except Exception as e:
        print(f"Error reopening task: {e}")
        socketio.emit("schedule_error", str(e))


@socketio.on("get_reminders_list")
def handle_get_reminders():
    """Emits the current list of reminders."""
    try:
        reminders = tools.get_reminders_json()
        socketio.emit("reminders_list_update", reminders)
    except Exception as e:
        print(f"Error getting reminders: {e}")
        socketio.emit("reminders_error", str(e))


@socketio.on("cancel_reminder_manual")
def cancel_reminder_manual(data: dict[str, Any]):
    try:
        tools.CancelReminder(data["reminder_id"], data["forever_or_next"])
    except Exception as e:
        print(f"Error getting reminders: {e}")
        socketio.emit("reminders_error", str(e))


@app.route("/favicon.ico")
def favicon():
    return redirect(url_for("static", filename="favicon.ico"), code=302)


@app.route("/")
def root():
    return render_template("index.html")


if __name__ == "__main__":
    chat_history_file = os.path.join(config.AI_DIR, "chat_history.json")
    chat_history.load_from_json(chat_history_file)
    notification_file = os.path.join(config.AI_DIR, "notifications.json")
    notification.notifications.load_from_json(notification_file)
    lschedule.schedule = lschedule.Schedule.load_from_json(
        config.AI_DIR / "schedule.json"
    )
    mail_checker = threading.Thread(target=start_checking_mail, daemon=True)
    mail_checker.start()
    try:
        reminder_runer = threading.Thread(target=tools.run_reminders, daemon=True)
        reminder_runer.start()
        socketio.run(app, host="127.0.0.1", port=5000, debug=True, use_reloader=False)
    finally:
        chat_history.save_to_json(chat_history_file)
        notification.notifications.save_to_json(notification_file)
        lschedule.schedule.save_to_json(config.AI_DIR / "schedule.json")
        tools.save_jobs()
        print("Chat history saved.")
...
