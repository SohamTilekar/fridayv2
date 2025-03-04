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
import json
import os
import base64
import time
import datetime

app = Flask("Friday")
socketio = SocketIO(app)

client = genai.Client(api_key=config.GOOGLE_API)

google_search_tool = types.Tool(
    google_search=types.GoogleSearch()
)


class File:
    type: str  # mime types
    content: bytes | str
    filename: str
    # whether the current attachment is the summary of the previous attachment
    is_summary: bool = False
    id: str
    cloud_uri: Optional[types.File] = None  # URI of the file in the cloud

    def __init__(self, content: bytes | str, type: str, filename: str, cloud_uri: Optional[types.File] = None, id: Optional[str] = None, is_summary: bool = False):
        self.content = content
        self.type = type
        self.filename = filename
        # Use the new method to generate a valid ID
        self.id = str(uuid.uuid4()) if id is None else id
        self.cloud_uri = cloud_uri
        self.is_summary = is_summary

    def delete(self):
        if self.cloud_uri and self.is_expiration_valid(self.cloud_uri.expiration_time):
            client.files.delete(name=self.cloud_uri.name)  # type: ignore

    @staticmethod
    def _generate_valid_video_file_id():
        """Generates a valid ID that conforms to the naming requirements."""
        # Generate a UUID, convert to string, make lowercase, and replace invalid characters with dashes.
        base_id = str(uuid.uuid4()).lower()[:35]
        # Ensure the ID doesn't start or end with a dash.  Add a prefix if needed.
        # Remove leading/trailing non-alphanumeric characters
        valid_id = re.sub(r'^[^a-z0-9]+|[^a-z0-9]+$', '', base_id)
        if not valid_id:
            # Default ID if the UUID generates an empty string after cleaning.
            valid_id = "file-id"
        return valid_id

    @staticmethod
    def is_expiration_valid(expiration_time: datetime.datetime | None) -> bool:
        if expiration_time is None:
            return True
        now = datetime.datetime.now()
        ten_minutes_from_now = now + datetime.timedelta(minutes=10)

        return expiration_time >= ten_minutes_from_now

    def for_ai(self, msg: Optional["Message"] = None) -> types.Part:
        if self.is_summary:
            return types.Part.from_text(text=f"\nFile Name: {self.filename}\nFile Type: {self.type.split('/')[0]}\nFile Summary: {self.content}")
        elif msg is None:
            raise TypeError("msg Paramiter of is not provided")
        if self.type.startswith("text/"):
            # Decode text files
            # type: ignore
            return types.Part.from_text(text=f"\nFile Name: {self.filename}\nFile Content: {self.content.decode('utf-8')}")
        elif self.type.startswith(("image/", "video/", "application/pdf")):
            # Use cloud URI if available, otherwise upload
            if self.cloud_uri and self.is_expiration_valid(self.cloud_uri.expiration_time):
                return self.cloud_uri  # type: ignore

            if self.type.startswith("image/"):
                prefix = "Processing Image:"
            elif self.type.startswith("video/"):
                prefix = "Processing Video:"
            else:
                prefix = "Processing PDF:"

            for attempt in range(config.MAX_RETRIES):
                try:
                    msg.content = f"{prefix} {self.filename}"
                    update_chat_with_response(msg)
                    self.cloud_uri = client.files.upload(file=BytesIO(self.content), config={  # type: ignore
                                                         "display_name": self.filename, "mime_type": self.type})
                    # Check whether the file is ready to be used.
                    while self.cloud_uri.state.name == "PROCESSING":  # type: ignore
                        time.sleep(1)
                        self.cloud_uri = client.files.get(
                            name=self.cloud_uri.name)  # type: ignore
                    if self.cloud_uri.state.name == "FAILED":  # type: ignore
                        # type: ignore
                        raise ValueError(self.cloud_uri.state.name)
                    msg.content = ""
                    update_chat_with_response(msg)
                    return self.cloud_uri  # type: ignore
                except Exception:
                    if attempt < config.MAX_RETRIES - 1:
                        time.sleep(config.RETRY_DELAY)
                    else:
                        raise  # Re-raise the exception to be caught in completeChat
        raise ValueError(f"Unsported File Type: {
                         self.type} of file {self.filename}")

    def for_sumarizer(self) -> list[types.Part]:
        if self.is_summary:
            return [self.for_ai()]
        if self.type.startswith("text/"):
            # Decode text files
            # type: ignore
            return [types.Part.from_text(text=f"\nname: {self.filename}\nid: {self.id}\nFile_Content: {self.content.decode('utf-8')}")]
        elif self.type.startswith(("image/", "video/", "application/pdf")):
            # Use cloud URI if available, otherwise upload
            if self.cloud_uri and self.is_expiration_valid(self.cloud_uri.expiration_time):
                # type: ignore
                return [types.Part.from_text(text=f"\nFileID: {self.id}"), self.cloud_uri]
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
                        # type: ignore
                        raise ValueError(self.cloud_uri.state.name)
                    # type: ignore
                    return [types.Part.from_text(text=f"\nFileID: {self.id}"), self.cloud_uri]
                except Exception:
                    if attempt < config.MAX_RETRIES - 1:
                        time.sleep(config.RETRY_DELAY)
                    else:
                        raise  # Re-raise the exception to be caught in completeChat
        raise ValueError(f"Unsported File Type: {
                         self.type} of file {self.filename}")

    def jsonify(self) -> dict:
        return {
            "type": self.type,
            "filename": self.filename,
            # type: ignore
            "content": base64.b64encode(self.content).decode('utf-8', errors='ignore'),
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
            types.File.model_validate(data.get('cloud_uri')) if data.get(
                'cloud_uri') else None,
            data.get('id', ''),
            data.get('is_summary', False)
        )


class GroundingSupport:
    grounding_chunk_indices: list[int]
    # dict[{"start_index", int}, {"end_index", int}, {"text", str}]
    segment: dict[str, int | str]

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
        return GroundingSupport(data["grounding_chunk_indices"], data["segment"])


class GroundingMetaData:
    first_offset: int
    rendered_content: str
    # list[tuple[str: title, str: uri]]
    grounding_chuncks: list[tuple[str, str]]
    grounding_supports: list[GroundingSupport]

    def __init__(self,
                 grounding_chuncks: list[tuple[str, str]],
                 grounding_supports: list[GroundingSupport],
                 first_offset: int = 0,
                 rendered_content: str = "",
                 ):
        self.grounding_chuncks = grounding_chuncks
        self.grounding_supports = grounding_supports
        self.first_offset = first_offset
        self.rendered_content = rendered_content

    def jsonify(self) -> dict:
        return {
            "first_offset": self.first_offset,
            "rendered_content": self.rendered_content,
            "grounding_chuncks": self.grounding_chuncks,
            "grounding_supports": [gsp.jsonify() for gsp in self.grounding_supports],
        }

    @staticmethod
    def from_jsonify(data: dict):
        return GroundingMetaData(data["grounding_chuncks"],
                                 [GroundingSupport.from_jsonify(
                                     sup) for sup in data["grounding_supports"]],
                                 data["first_offset"],
                                 data.get("rendered_content", ""))


class Message:
    role: Literal["model", "user"]
    content: str
    time_stamp: datetime.datetime
    attachments: list[File]
    grounding_metadata: GroundingMetaData
    id: str
    is_summary: bool = False

    def __init__(self, content: str, role: Literal["model", "user"], grounding_metadata: Optional[GroundingMetaData] = None, attachments: Optional[list[File]] = None, time_stamp: Optional[datetime.datetime] = None, is_summary: bool = False, id:Optional[str] = None):
        self.time_stamp = time_stamp if time_stamp else datetime.datetime.now()
        self.content = content
        self.role = role
        self.id = str(uuid.uuid4()) if id is None else id
        self.attachments = attachments if attachments is not None else []
        self.grounding_metadata = grounding_metadata if grounding_metadata else GroundingMetaData([
        ], [])
        self.is_summary = is_summary
    def delete(self):
        for file in self.attachments:
            file.delete()

    def getAttachment(self, ID: str):
        for file in self.attachments:
            if file.id == ID:
                return file
        raise ValueError(f"Attachment of ID: `{ID}` not found in message of ID: {self.id}")

    def summarizeAttachment(self, ID: str, summary: str):
        for file in self.attachments:
            if file.id == ID:
                file.content = summary
                file.is_summary = True
                break

    def deleteAttachment(self, ID: str):
        for idx, file in enumerate(self.attachments):
            if file.id == ID:
                file.delete()
                del self.attachments[idx]
                break

    def for_ai(self, msg: Optional["Message"] = None) -> types.Content:
        if self.is_summary:
            return types.Part.from_text(text="Message Summary: " + self.content)  # type: ignore
        elif msg is None:
            raise TypeError("msg Paramiter of is not provided")
        ai_content: list[types.Part] = []
        for file in self.attachments:
            ai_content.append(file.for_ai(msg))
        ai_content.append(types.Part.from_text(
            text=self.time_stamp.strftime("%H:%M")))
        if self.content:
            ai_content.append(types.Part.from_text(text=self.content))
        return types.Content(parts=ai_content, role=self.role)

    def for_sumarizer(self) -> types.Content:
        ai_content: list[types.Part] = []
        ai_content.append(types.Part.from_text(
            text=self.time_stamp.strftime(f"MessageID: {self.id}")))
        ai_content.append(types.Part.from_text(
            text=self.time_stamp.strftime("on %d-%m-%Y at %H")))
        for file in self.attachments:
            ai_content.extend(file.for_sumarizer())
        if self.content:
            ai_content.append(types.Part.from_text(text=self.content))
        return types.Content(parts=ai_content, role=self.role)

    def jsonify(self) -> dict[str, str | Literal["model", "user"] | list | Any]:
        return {
            "role": self.role,
            "content": self.content,
            "grounding_metadata": self.grounding_metadata.jsonify(),
            "id": self.id,
            "time_stamp": self.time_stamp.isoformat(),
            "attachments": [file.jsonify() for file in self.attachments],
            "is_summary": self.is_summary,
        }

    @staticmethod
    def from_jsonify(data: dict):
        attachments = [File.from_jsonify(file_data)
                       for file_data in data.get('attachments', [])]
        return Message(
            data.get('content', ''),
            data.get('role', 'user'),
            GroundingMetaData.from_jsonify(data.get("grounding_metadata", {})),
            attachments,
            datetime.datetime.fromisoformat(
                data.get("time_stamp", datetime.datetime.now().isoformat())),
            data.get('is_summary', False),
            data.get('id', "")
        )


class ChatHistory:
    chat: list[Message] = []

    def append(self, msg: Message):
        self.chat.append(msg)
        socketio.emit("chat_update", self.jsonify())

    def delete_message(self, msg_id):
        new_chat = []
        for msg in self.chat:
            if msg.id == msg_id:
                msg.delete()
            else:
                new_chat.append(msg)
        self.chat = new_chat
        socketio.emit("chat_update", self.jsonify())

    def __len__(self):
        return len(self.chat)

    def __getitem__(self, idx: int):
        return self.chat[idx]

    def getMsg(self, ID: str) -> Message:
        for msg in self.chat:
            if msg.id == ID:
                return msg
        raise ValueError(f"Message of ID: `{ID}` not found")

    def setMsg(self, ID: str, new_msg: Message):
        for msg in self.chat:
            if msg.id == ID:
                msg = new_msg
                return
        raise ValueError(f"Message of ID: `{ID}` not found")

    def getMsgRange(self, Start_ID: str, End_ID: str) -> Iterator[Message]:
        idx = 0
        while idx < len(self.chat):
            if self.chat[idx].id == Start_ID:
                while idx < len(self.chat):
                    if self.chat[idx].id == End_ID:
                        return self.chat[idx]
                    else:
                        yield self.chat[idx]
                        idx += 1
                raise ValueError(f"Message of ID: `{End_ID}` not found")
            idx += 1
        raise ValueError(f"Message of ID: `{Start_ID}` not found")

    def delMsgRange(self, Start_ID: str, End_ID: str) -> None:
        """Ignore Start_ID msg, delete from Start_ID+1..End_ID"""
        idx = 0
        while idx < len(self.chat):
            if self.chat[idx].id == Start_ID:
                while idx < len(self.chat):
                    if self.chat[idx].id == End_ID:
                        del self.chat[idx]
                        return
                    else:
                        del self.chat[idx]
                        idx += 1
                raise ValueError(f"Message of ID: `{End_ID}` not found")
            idx += 1
        raise ValueError(f"Message of ID: `{Start_ID}` not found")

    def replaceMsgRange(self, Start_ID: str, End_ID: str, msg: Message) -> None:
            idx = 0
            while idx < len(self.chat):
                if self.chat[idx].id == Start_ID:
                    self.chat[idx] = msg
                    idx += 1
                    while idx < len(self.chat):
                        if self.chat[idx].id == End_ID:
                            del self.chat[idx]
                            return
                        else:
                            del self.chat[idx]
                            idx += 1
                    raise ValueError(f"Message of ID: `{End_ID}` not found")
                idx += 1
            raise ValueError(f"Message of ID: `{Start_ID}` not found")

    def for_ai(self, ai_msg: Message) -> types.ContentListUnion:
        result: types.ContentListUnion = []
        for msg in self.chat:
            result.append(msg.for_ai(ai_msg))
        return result

    def for_sumarizer(self) -> types.ContentListUnion:
        result: types.ContentListUnion = []
        for msg in self.chat:
            result.append(msg.for_sumarizer())
        return result

    def jsonify(self) -> list[dict[str, str | Literal["model", "user"] | list]]:
        return [msg.jsonify() for msg in self.chat]

    def save_to_json(self, filepath: str):
        """Saves the chat history to a JSON file."""
        data = [msg.jsonify() for msg in self.chat]
        with open(filepath, 'w') as f:
            json.dump(data, f, indent=4)

    def load_from_json(self, filepath: str):
        """Loads the chat history from a JSON file."""
        try:
            with open(filepath, 'r') as f:
                data = json.load(f)
                self.chat = []
                for msg_data in data:
                    msg = Message.from_jsonify(msg_data)
                    self.chat.append(msg)
        except FileNotFoundError:
            print("Chat history file not found. Starting with an empty chat.")
        except json.JSONDecodeError:
            print("Error decoding chat history. Starting with an empty chat.")


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
        update_chat_with_response(ai_response)


def append_user_message(message: str, files: list[File]):
    """Appends the user's message and files to the chat history."""
    chat_history.append(Message(message, "user", None, files))


def get_ai_response() -> Message:
    """
    Gets the AI's response from the Gemini model, handling retries and token limits.
    """
    # Append a placeholder for the AI reply
    chat_history.append(Message("", "model"))
    msg_index = len(chat_history) - 1
    msg = chat_history[msg_index]

    for attempt in range(config.MAX_RETRIES):
        try:
            return generate_content_with_retry(msg)
        except Exception as e:
            if attempt < config.MAX_RETRIES - 1:
                time.sleep(config.RETRY_DELAY*attempt)
            else:
                handle_generation_failure(msg, e)
                return msg
    return msg


def generate_content_with_retry(msg: Message) -> Message:
    """
    Generates content from the Gemini model with retry logic for token limits.
    """
    x = 0
    while True:
        x += 1
        response = client.models.generate_content_stream(
            model="gemini-2.0-flash",
            contents=chat_history.for_ai(msg),
            config=types.GenerateContentConfig(
                system_instruction=prompt.SYSTEM_INSTUNCTION,
                temperature=0.25,
                max_output_tokens=8192,
                top_p=0.2,
                tools=[google_search_tool],
            )
        )

        last_content: types.GenerateContentResponse | None = None
        for content in response:
            last_content = content
            if content.text:
                msg.content += content.text
                update_chat_with_response(msg)

        if last_content:
            process_grounding_metadata(msg, last_content)

        tokens: int = client.models.count_tokens(
            model="gemini-2.0-flash", contents=msg.content).total_tokens or 0
        if tokens >= 8150 * x:
            continue  # Recalling AI cz mostlikely max output tokens are reached
        break

    msg.time_stamp = datetime.datetime.now()
    return msg


def process_grounding_metadata(msg: Message, last_content: types.GenerateContentResponse):
    """
    Processes grounding metadata from the AI response.
    """
    if last_content.candidates and last_content.candidates[0].grounding_metadata:
        metadata = last_content.candidates[0].grounding_metadata

        if metadata.search_entry_point:
            msg.grounding_metadata.rendered_content = metadata.search_entry_point.rendered_content or ""

        if metadata.grounding_chunks:
            for chunk in metadata.grounding_chunks:
                if chunk.web:
                    msg.grounding_metadata.grounding_chuncks.append(
                        (chunk.web.title, chunk.web.uri))  # type: ignore

        if metadata.grounding_chunks and metadata.grounding_supports and metadata.web_search_queries:
            process_grounding_supports(msg, metadata, last_content)


def process_grounding_supports(msg: Message, metadata: types.GroundingMetadata, last_content: types.GenerateContentResponse):
    """
    Processes grounding support information and updates the message.
    """
    first = True
    for support in metadata.grounding_supports:  # type: ignore
        start_index = msg.content.find(support.segment.text)  # type: ignore
        if start_index == -1:
            escaped_target = re.escape(msg.content)
            # Create a regex pattern that allows for extra spaces and minor variations
            # Allow any amount of whitespace between chars
            pattern = r'\s*'.join(list(escaped_target))
            match = re.search(
                pattern, support.segment.text or "")  # type: ignore
            if match:
                return match.start()
            else:
                print(msg.content, support.segment.text)  # type: ignore
                continue

        if first:
            msg.grounding_metadata.first_offset = start_index - \
                support.segment.start_index  # type: ignore
            first = False

        msg.grounding_metadata.grounding_supports.append(
            GroundingSupport(support.grounding_chunk_indices, {  # type: ignore
                "text": support.segment.text,  # type: ignore
                "start_index": start_index,
                # type: ignore
                "end_index": start_index + len(support.segment.text)
            })  # type: ignore
        )
    update_chat_with_response(msg)


def handle_generation_failure(msg: Message, error: Exception):
    """
    Handles the failure to generate a response from the AI model.
    """
    error_message = f"Failed to generate response after multiple retries: {
        str(error)}"
    msg.content = error_message
    update_chat_with_response(msg)


def update_chat_with_response(msg: Message):
    """
    Updates the chat history and emits the updated message.
    """
    socketio.emit("updated_msg", msg.jsonify())


def SummarizeAttachment(AttachmentID: str, MessageID: str):
    """\
    Summarizes the content of a specific attachment, linking the summary to the original attachment and message.
    Use this for attachments that are no longer actively referenced but might contain valuable background information.
    """
    print(f"SummarizeAttachment: {AttachmentID=}, {MessageID=}")
    for tri in range(config.MAX_RETRIES):
        try:
            chat: types.ContentListUnion = [
                types.Content(
                    role="user",
                    parts=[
                        *chat_history.getMsg(MessageID).getAttachment(AttachmentID).for_sumarizer(),
                        types.Part.from_text(
                            text="Sumarize the Above File Attachment While Preserving the Details, Facts")
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
            responce = client.models.generate_content(
                model="gemini-2.0-flash-lite",
                contents=chat,
                config=types.GenerateContentConfig(
                    system_instruction=prompt.ATTACHMENT_SUMMARIZER_SYSTEM_INSTUNCTION,
                    temperature=0,
                )
            )
            file = chat_history.getMsg(MessageID).getAttachment(AttachmentID)
            file.is_summary = True
            if responce.text:
                file.content = responce.text
                print(f"Summarized Attachment: {AttachmentID=}, {MessageID=}")
                return f"Summarized Attachment: {AttachmentID=}, {MessageID=}"
            print(f" dident Summarized Attachment: {AttachmentID=}, {MessageID=}")
            return f" dident Summarized Attachment: {AttachmentID=}, {MessageID=}"
        except Exception as e:
            if config.MAX_RETRIES - 1 > tri:
                print("Attempt: ", tri, "Fail: ", e)
                continue
            else:
                return str(e)
    return ""

def SummarizeMessage(MessageID: str):
    """\
    Summarizes the content of a specific message with its attachments.
    Use this for verbose or lengthy messages that contain information that can be condensed without losing critical meaning.
    """
    for tri in range(config.MAX_RETRIES):
        try:
            chat: types.ContentListUnion = [
                chat_history.getMsg(MessageID).for_sumarizer(),
                types.Content(
                    role="user",
                    parts=[
                        types.Part.from_text(
                            text="Sumarize the Above Message with its Attachment While Preserving the Details, Facts")
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
            responce = client.models.generate_content(
                model="gemini-2.0-flash-lite",
                contents=chat,
                config=types.GenerateContentConfig(
                    system_instruction=prompt.MESSAGE_SUMMARIZER_SYSTEM_INSTUNCTION,
                    temperature=0,
                )
            )
            msg = chat_history.getMsg(MessageID)
            msg.is_summary = True
            if responce.text:
                msg.content = responce.text
                print("Sumarized message " + MessageID)
                return "Sumarized message " + MessageID
            print("dident Summarized message " + MessageID)
            return "dident Summarized message " + MessageID
        except Exception as e:
            if config.MAX_RETRIES - 1 > tri:
                print("Attempt: ", tri, "Fail: ", e)
                continue
            else:
                return str(e)
    return ""

def SummarizeHistory(StartMessageID: str, EndMessageID: str):
    """\
    Summarizes a range of messages within StartMessageID & EndMessageID ( Including StartMessageID & EndMessageID).
    Use this for older conversations that are no longer directly relevant but provide useful context.
    """
    for tri in range(config.MAX_RETRIES):
        try:
            chat: types.ContentListUnion = [
                *(msg.for_sumarizer()
                  for msg in chat_history.getMsgRange(StartMessageID, EndMessageID)),
                types.Content(
                    role="user",
                    parts=[
                        types.Part.from_text(
                            text="Sumarize the Above Messages with its Attachment While Preserving the Details, Facts")
                    ]
                ),
                types.Content(
                    role="model",
                    parts=[
                        types.Part.from_text(
                            text="Message & its attachment History summary:\n")
                    ]
                )
            ]
            responce = client.models.generate_content(
                model="gemini-2.0-flash-lite",
                contents=chat,
                config=types.GenerateContentConfig(
                    system_instruction=prompt.MESSAGE_HISTORY_SUMMARIZER_SYSTEM_INSTUNCTION,
                    temperature=0,
                )
            )
            if responce.text:
                chat_history.replaceMsgRange(StartMessageID, EndMessageID, Message(responce.text, "user"))
                print(f"Success Fully Sumarize messages from {StartMessageID} to {EndMessageID}")
                return f"Success Fully Sumarize messages from {StartMessageID} to {EndMessageID}"
            print(f"dident Sumarize messages from {StartMessageID} to {EndMessageID}")
            return f"dident Sumarize messages from {StartMessageID} to {EndMessageID}"
        except Exception as e:
            if config.MAX_RETRIES - 1 > tri:
                print("Attempt: ", tri, "Fail: ", e)
                continue
            else:
                return str(e)
    return ""

def RemoveAttachment(AttachmentID: str, MessageID: str):
    """\
    Removes a specific attachment from a message.
    Use this for attachments that are clearly irrelevant to the current conversation or have become obsolete.
    """
    print(f"RemoveAttachment: {AttachmentID=}, {MessageID=}")
    chat_history.getMsg(MessageID).deleteAttachment(AttachmentID)
    return f"RemoveAttachment: {AttachmentID=}, {MessageID=}"

def RemoveMessage(MessageID: str):
    """\
    Removes an entire message from the chat history & its attachments.
    Use this sparingly and only for messages that are demonstrably irrelevant and contribute little to the overall context.
    If user ask AI about some thing & the curent chat is irrelivant to it then use it, like user ask what is xyz & no longer relivant
    """
    print(f"RemoveAttachment: {MessageID=}")
    chat_history.delete_message(MessageID)
    return f"RemoveAttachment: {MessageID=}"

def RemoveMessageHistory(StartMessageID: str, EndMessageID: str):
    """\
    Removes a range of messages whith & after StartMessageID & whith & before EndMessageID.
    Use this for older conversations that are demonstrably irrelevant and contribute little to the overall context.
    """
    print(f"RemoveAttachment: {StartMessageID=}, {EndMessageID=}")
    chat_history.delMsgRange(StartMessageID, EndMessageID)
    return f"RemoveAttachment: {StartMessageID=}, {EndMessageID=}"


@app.route('/favicon.ico')
def favicon():
    return redirect(url_for('static', filename='favicon.ico'), code=302)

# Render the main chat frontend


@app.route('/')
def root():
    return render_template('index.html')


# ID & [its chuncks with their idx & is fully uploded (true if video is fully uploded otherwise false)]
videos: dict[str, tuple[dict[int, str], bool]] = {}


@socketio.on("start_upload_video")
def start_upload_video(id: str):
    videos[id] = ({}, False)


@socketio.on("upload_video_chunck")
def upload_video_chunck(data: dict[str, str | int]):
    id: str = data["id"]  # type: ignore
    chunck: str = data["chunck"]  # type: ignore
    idx: int = data["idx"]  # type: ignore
    videos[id][0][idx] = chunck


@socketio.on("end_upload_video")
def end_upload_video(id: str):
    videos[id] = (videos[id][0], True)


@socketio.on("send_message")
def handle_send_message(data):
    message = data.get("message", "")
    file_attachments = []
    file_data_list = data.get("files", [])

    for file_data in file_data_list:
        file_type: str = file_data.get("type")
        filename: str = file_data.get("filename")

        if file_type.startswith(("text/", "image/")):
            content_base64: str = file_data.get("content")
            file_content = base64.b64decode(content_base64)
            file_attachments.append(File(file_content, file_type, filename))
        elif file_type.startswith(("video/")):
            id: str = file_data.get("id")
            while (not videos.get(id)):
                time.sleep(0.1)
            while (not videos[id][1]):
                time.sleep(0.2)
            vid = videos[id][0]
            x = 0
            content: str = ""
            while (vid.get(x) is not None):
                content += vid[x]
                x += 1
            decoded_content = base64.b64decode(content)
            file_attachments.append(File(
                decoded_content, file_type, filename, None, File._generate_valid_video_file_id()))
            del videos[id]

    complete_chat(message, file_attachments)


@socketio.on("get_chat_history")
def handle_get_chat_history():
    socketio.emit("chat_update", chat_history.jsonify())


@socketio.on("delete_message")
def handle_delete_message(data):
    msg_id = data.get("message_id")
    chat_history.delete_message(msg_id)
    socketio.emit("chat_update", chat_history.jsonify())


@socketio.on("srink_chat")
def reduceTokensUsage():
    """Reduces token usage of the chat history, with retry logic.

    Returns:
        bool: True on success, False on failure.
    """
    chat = chat_history.for_sumarizer()
    chat.append(types.Content(parts=[types.Part(text=prompt.TOKEN_REDUCER_USER_INSTUNCTION)], role="user"))  # type: ignore
    print(chat)
    for attempt in range(config.MAX_RETRIES):
        try:
            while True:
                response = client.models.generate_content(
                    model="gemini-2.0-flash",
                    contents=chat,
                    config=types.GenerateContentConfig(
                        system_instruction=prompt.TOKEN_REDUCER_SYSTEM_INSTUNCTION,
                        temperature=0,
                        tools=[
                            SummarizeAttachment,
                            SummarizeMessage,
                            SummarizeHistory,
                            RemoveAttachment,
                            RemoveMessage,
                            RemoveMessageHistory
                        ],
                        automatic_function_calling=types.AutomaticFunctionCallingConfig(
                            disable=True
                        ),
                    )
                )
                content = types.Content(role="user")  # type: ignore
                call: bool = False
                for part in content.parts:  # type: ignore
                    call = True
                    if part.function_call:
                        if part.function_call.name == "SummarizeAttachment":
                            try:
                                content.parts.append( # type: ignore
                                    types.Part(
                                        function_response=types.FunctionResponse(
                                            id=part.function_call.id,
                                            name="SummarizeAttachment",
                                            response={"output": SummarizeAttachment(*part.function_call.args)} # type: ignore
                                        )
                                    )
                                )  # type: ignore
                            except Exception as e:
                                content.parts.append( # type: ignore
                                    types.Part(
                                        function_response=types.FunctionResponse(
                                            id=part.function_call.id,
                                            name="SummarizeAttachment",
                                            response={"output": e} # type: ignore
                                        )
                                    )
                                )  # type: ignore
                        elif part.function_call.name == "SummarizeMessage":
                            try:
                                content.parts.append( # type: ignore
                                    types.Part(
                                        function_response=types.FunctionResponse(
                                            id=part.function_call.id,
                                            name="SummarizeMessage",
                                            response={"output": SummarizeMessage(*part.function_call.args)} # type: ignore
                                        )
                                    )
                                )  # type: ignore
                            except Exception as e:
                                content.parts.append( # type: ignore
                                    types.Part(
                                        function_response=types.FunctionResponse(
                                            id=part.function_call.id,
                                            name="SummarizeMessage",
                                            response={"output": e} # type: ignore
                                        )
                                    )
                                )  # type: ignore
                        elif part.function_call.name == "SummarizeHistory":
                            try:
                                content.parts.append( # type: ignore
                                    types.Part(
                                        function_response=types.FunctionResponse(
                                            id=part.function_call.id,
                                            name="SummarizeHistory",
                                            response={"output": SummarizeHistory(*part.function_call.args)} # type: ignore
                                        )
                                    )
                                )  # type: ignore
                            except Exception as e:
                                content.parts.append( # type: ignore
                                    types.Part(
                                        function_response=types.FunctionResponse(
                                            id=part.function_call.id,
                                            name="SummarizeHistory",
                                            response={"output": e} # type: ignore
                                        )
                                    )
                                )  # type: ignore
                        elif part.function_call.name == "RemoveAttachment":
                            try:
                                content.parts.append( # type: ignore
                                    types.Part(
                                        function_response=types.FunctionResponse(
                                            id=part.function_call.id,
                                            name="RemoveAttachment",
                                            response={"output": RemoveAttachment(*part.function_call.args)} # type: ignore
                                        )
                                    )
                                )  # type: ignore
                            except Exception as e:
                                content.parts.append( # type: ignore
                                    types.Part(
                                        function_response=types.FunctionResponse(
                                            id=part.function_call.id,
                                            name="RemoveAttachment",
                                            response={"output": e} # type: ignore
                                        )
                                    )
                                )  # type: ignore
                        elif part.function_call.name == "RemoveMessage":
                            try:
                                content.parts.append( # type: ignore
                                    types.Part(
                                        function_response=types.FunctionResponse(
                                            id=part.function_call.id,
                                            name="RemoveMessage",
                                            response={"output": RemoveMessage(*part.function_call.args)} # type: ignore
                                        )
                                    )
                                )  # type: ignore
                            except Exception as e:
                                content.parts.append( # type: ignore
                                    types.Part(
                                        function_response=types.FunctionResponse(
                                            id=part.function_call.id,
                                            name="RemoveMessage",
                                            response={"output": e} # type: ignore
                                        )
                                    )
                                )  # type: ignore
                        elif part.function_call.name == "RemoveMessageHistory":
                            try:
                                content.parts.append( # type: ignore
                                    types.Part(
                                        function_response=types.FunctionResponse(
                                            id=part.function_call.id,
                                            name="RemoveMessageHistory",
                                            response={"output": RemoveMessageHistory(*part.function_call.args)} # type: ignore
                                        )
                                    )
                                )  # type: ignore
                            except Exception as e:
                                content.parts.append( # type: ignore
                                    types.Part(
                                        function_response=types.FunctionResponse(
                                            id=part.function_call.id,
                                            name="RemoveMessageHistory",
                                            response={"output": e} # type: ignore
                                        )
                                    )
                                )  # type: ignore
                        else:
                            content.parts.append( # type: ignore
                                types.Part(
                                    function_response=types.FunctionResponse(
                                        id=part.function_call.id,
                                        name=part.function_call.name,
                                        response={"output": f"Unknown Function of name {part.function_call.name}"} # type: ignore
                                    )
                                )
                            )  # type: ignore
                chat = chat_history.for_sumarizer()
                chat.append(response.candidates[0].content)  # type: ignore
                chat.append(content)  # type: ignore
                print(response)
                if call:
                    continue
                else:
                    break
            return True  # Return True on success
        except Exception as e:
            print(f"Attempt {attempt + 1} failed: ", e)
            if attempt < config.MAX_RETRIES - 1:
                time.sleep(attempt*config.RETRY_DELAY)  # Wait before retrying
            else:
                print("Max retries reached. Failed to reduce token usage.")
                return False  # Return False on failure


if __name__ == "__main__":
    chat_history_file = os.path.join(config.DATA_DIR, "chat_history.json")
    chat_history.load_from_json(chat_history_file)
    try:
        socketio.run(app, host='127.0.0.1', port=5000,
                     debug=True, use_reloader=False)
    finally:
        chat_history_file = os.path.join(config.DATA_DIR, "chat_history.json")
        chat_history.save_to_json(chat_history_file)
        print("Chat history saved.")
