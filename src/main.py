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
import json
import os
import base64
import time
import datetime
import utils

app = Flask("Friday")
socketio = SocketIO(app)

client = genai.Client(api_key=config.GOOGLE_API)

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

    def for_ai(self, msg: Optional["Message"] = None) -> types.Part:
        if self.is_summary:
            return types.Part.from_text(text=f"\nFile Name: {self.filename}\nFile Type: {self.type.split('/')[0]}\nFile Summary: {self.content}")
        elif msg is None:
            raise TypeError("msg Paramiter of is not provided")
        
        if self.type.startswith("text/"):
            return types.Part.from_text(text=f"\nFile Name: {self.filename}\nFile Content: {self.content.decode('utf-8')}") # type: ignore
        elif self.type.startswith(("image/", "video/") or self.type == "application/pdf"):
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
                    msg.content.append(Content(text=f"{prefix} {self.filename}", processing=True))
                    update_chat_with_response(msg)
                    self.cloud_uri = client.files.upload(file=BytesIO(self.content), config={"display_name": self.filename, "mime_type": self.type})  # type: ignore
                    # Check whether the file is ready to be used.
                    while self.cloud_uri.state.name == "PROCESSING":  # type: ignore
                        time.sleep(1)
                        self.cloud_uri = client.files.get(
                            name=self.cloud_uri.name)  # type: ignore
                    if self.cloud_uri.state.name == "FAILED":  # type: ignore
                        raise ValueError(self.cloud_uri.state.name)  # type: ignore
                    msg.content.pop()
                    update_chat_with_response(msg)
                    return self.cloud_uri  # type: ignore
                except Exception:
                    if attempt < config.MAX_RETRIES - 1:
                        time.sleep(config.RETRY_DELAY)
                    else:
                        raise  # Re-raise the exception to be caught in completeChat
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

    def jsonify(self) -> dict:
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

class Content:
    text: Optional[str] = None
    processing: bool = False
    attachment: Optional[File] = None
    grounding_metadata: Optional[GroundingMetaData] = None

    def __init__(self, text: Optional[str] = None, attachment: Optional[File] = None, grounding_metadata: Optional[GroundingMetaData] = None, processing: bool = False):
        self.text = text
        self.attachment = attachment
        self.grounding_metadata = grounding_metadata
        self.processing = processing

    def for_ai(self, msg: Optional["Message"] = None) -> types.Part:
        if self.text is not None:
            return types.Part(text=self.text)
        elif self.attachment is not None:
            return self.attachment.for_ai(msg)
        else:
            raise # Raise Appropriate Error

    def for_sumarizer(self) -> list[types.Part]:
        if self.text is not None:
            return [types.Part(text=self.text)]
        elif self.attachment is not None:
            return self.attachment.for_summarizer()
        else:
            raise # Raise Appropriate Error

    def jsonify(self):
        return {
            "text": self.text,
            "attachment": self.attachment.jsonify() if self.attachment else None,
            "grounding_metadata": self.grounding_metadata.jsonify() if self.grounding_metadata else None,
            "processing": self.processing
        }

    @staticmethod
    def from_jsonify(data: dict):
        return Content(
            text=data.get("text", ""),
            attachment=File.from_jsonify(data["attachment"]) if data.get("attachment") else None,
            grounding_metadata=GroundingMetaData.from_jsonify(data["grounding_metadata"]) if data.get("grounding_metadata") else None,
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

    def for_ai(self, msg: Optional["Message"] = None) -> types.Content:
        if self.is_summary:
            return types.Content(parts=[content.for_ai(msg) for content in self.content], role=self.role)  # type: ignore
        if msg is None:
            raise ValueError("msg parameter is required.")

        ai_contents: list[types.Part] = []
        for item in self.content:
            ai_contents.append(item.for_ai(msg))
        ai_contents.append(types.Part(text=self.time_stamp.strftime("%H:%M")))

        return types.Content(parts=ai_contents, role=self.role)

    def for_summarizer(self) -> types.Content:
        ai_content: list[types.Part] = [
            types.Part.from_text(text=f"MessageID: {self.id}"),
            types.Part.from_text(text=self.time_stamp.strftime("on %d-%m-%Y at %H")),
        ]
        for item in self.content:
            ai_content.extend(item.for_sumarizer())
        return types.Content(parts=ai_content, role=self.role)

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

    def for_ai(self, ai_msg: Message) -> list[types.Content]:
        result: list[types.Content] = []
        for msg in self.chat:
            result.append(msg.for_ai(ai_msg))
        return result

    def for_summarizer(self) -> list[types.Content]:
        result: list[types.Content] = []
        for msg in self.chat:
            result.append(msg.for_summarizer())
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


# Chat History Management

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

def update_chat_with_response(msg: Message):
    """
    Updates the chat history and emits the updated message.
    """
    socketio.emit("updated_msg", msg.jsonify())


# Gemini Model Interaction
@utils.retry()
def generate_content_with_retry(msg: Message) -> Message:
    """
    Generates content from the Gemini model with retry logic for token limits.
    """
    x = 0
    while True:
        x += 1
        response = client.models.generate_content_stream(
            model=config.CHAT_AI,
            contents=chat_history.for_ai(msg), # type: ignore
            config=types.GenerateContentConfig(
                system_instruction=prompt.SYSTEM_INSTUNCTION,
                temperature=config.CHAT_AI_TEMP,
                max_output_tokens=config.MAX_OUTPUT_TOKEN_LIMIT,
                tools=[types.Tool(google_search=types.GoogleSearch())],
                automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True, maximum_remote_calls=None),
            )
        )
        finish_reason: Optional[types.FinishReason] = None
        for content in response:
            if (content.candidates and content.candidates[0].content and content.candidates[0].content.parts):
                for part in content.candidates[0].content.parts:
                    if part.thought and part.text:
                        msg.thought += part.text
                    elif part.text:
                        if not msg.content or msg.content[-1].text is None:
                            msg.content.append(Content(text=part.text))
                        else:
                            msg.content[-1].text += part.text
                    else:
                        continue
                process_grounding_metadata(msg, content)
            update_chat_with_response(msg)
        if finish_reason == types.FinishReason.MAX_TOKENS:
            continue  # Recalling AI max output tokens are reached but AI want to Reply
        break

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

def process_grounding_supports(msg: Message, metadata: types.GroundingMetadata):
    """
    Processes grounding support information and updates the message.
    """
    if msg.content[-1].grounding_metadata is None:
        msg.content[-1].grounding_metadata = GroundingMetaData([], [])
    first = True
    for support in metadata.grounding_supports:  # type: ignore
        start_index = msg.content.find(support.segment.text)  # type: ignore
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
    update_chat_with_response(msg)

def handle_generation_failure(msg: Message, error: Exception):
    """
    Handles the failure to generate a response from the AI model.
    """
    error_message = f"Failed to generate response after multiple retries: {
        str(error)}"
    if not msg.content or msg.content[-1].text is None:
        msg.content.append(Content(text=error_message))
    else:
        msg.content[-1].text = error_message
    update_chat_with_response(msg)

# Token Reduction (Summarization/Removal)

@utils.retry()
def SummarizeAttachment(AttachmentID: str, MessageID: str):
    """\
    Summarizes the content of a specific attachment, linking the summary to the original attachment and message.
    Use this for attachments that are no longer actively referenced but might contain valuable background information.
    """
    chat: list[types.Content] = [
        types.Content(
            role="user",
            parts=[
                *chat_history.getMsg(MessageID).get_attachment(AttachmentID).for_summarizer(),
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
        model=config.SUMMARIZER_AI,
        contents=chat, # type: ignore
        config=types.GenerateContentConfig(
            system_instruction=prompt.ATTACHMENT_SUMMARIZER_SYSTEM_INSTUNCTION,
            temperature=0,
        )
    )
    file = chat_history.getMsg(MessageID).get_attachment(AttachmentID)
    file.is_summary = True
    if responce.text:
        file.content = responce.text
        return f"Summarized Attachment: {AttachmentID=}, {MessageID=}"
    return f" dident Summarized Attachment: {AttachmentID=}, {MessageID=}"

@utils.retry()
def SummarizeMessage(MessageID: str):
    """\
    Summarizes the content of a specific message with its attachments.
    Use this for verbose or lengthy messages that contain information that can be condensed without losing critical meaning.
    """
    chat: list[types.Content] = [
        chat_history.getMsg(MessageID).for_summarizer(),
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
        model=config.SUMMARIZER_AI,
        contents=chat, # type: ignore
        config=types.GenerateContentConfig(
            system_instruction=prompt.MESSAGE_SUMMARIZER_SYSTEM_INSTUNCTION,
            temperature=0,
        )
    )
    msg = chat_history.getMsg(MessageID)
    msg.is_summary = True
    if responce.text:
        if not msg.content or msg.content[-1].text is None:
            msg.content.append(Content(text=responce.text))
        else:
            msg.content[-1].text += responce.text
        return "Sumarized message " + MessageID
    return "dident Summarized message " + MessageID

@utils.retry()
def SummarizeHistory(StartMessageID: str, EndMessageID: str):
    """\
    Summarizes a range of messages within StartMessageID & EndMessageID ( Including StartMessageID & EndMessageID).
    Use this for older conversations that are no longer directly relevant but provide useful context.
    """
    chat: list[types.Content] = [
        *(msg.for_summarizer()
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
        model=config.SUMMARIZER_AI,
        contents=chat, # type: ignore
        config=types.GenerateContentConfig(
            system_instruction=prompt.MESSAGE_HISTORY_SUMMARIZER_SYSTEM_INSTUNCTION,
            temperature=0,
        )
    )
    if responce.text:
        chat_history.replaceMsgRange(StartMessageID, EndMessageID, Message([Content(text=responce.text)], "user"))
        return f"Success Fully Sumarize messages from {StartMessageID} to {EndMessageID}"
    return f"dident Sumarize messages from {StartMessageID} to {EndMessageID}"

def RemoveAttachment(AttachmentID: str, MessageID: str):
    """\
    Removes a specific attachment from a message.
    Use this for attachments that are clearly irrelevant to the current conversation or have become obsolete.
    """
    chat_history.getMsg(MessageID).delete_attachment(AttachmentID)
    return f"RemoveAttachment: {AttachmentID=}, {MessageID=}"

def RemoveMessage(MessageID: str):
    """\
    Removes an entire message from the chat history & its attachments.
    Use this sparingly and only for messages that are demonstrably irrelevant and contribute little to the overall context.
    If user ask AI about some thing & the curent chat is irrelivant to it then use it, like user ask what is xyz & no longer relivant
    """
    chat_history.delete_message(MessageID)
    return f"RemoveAttachment: {MessageID=}"

def RemoveMessageHistory(StartMessageID: str, EndMessageID: str):
    """\
    Removes a range of messages whith & after StartMessageID & whith & before EndMessageID.
    Use this for older conversations that are demonstrably irrelevant and contribute little to the overall context.
    """
    chat_history.delMsgRange(StartMessageID, EndMessageID)
    return f"RemoveAttachment: {StartMessageID=}, {EndMessageID=}"


# SocketIO Event Handlers

@socketio.on("srink_chat")
def reduceTokensUsage():
    """Reduces token usage of the chat history, with retry logic.

    Returns:
        bool: True on success, False on failure.
    """
    chat = chat_history.for_summarizer()
    chat.append(types.Content(parts=[types.Part(text=prompt.TOKEN_REDUCER_USER_INSTUNCTION)], role="user"))

    function_map = {
        "SummarizeAttachment": SummarizeAttachment,
        "SummarizeMessage": SummarizeMessage,
        "SummarizeHistory": SummarizeHistory,
        "RemoveAttachment": RemoveAttachment,
        "RemoveMessage": RemoveMessage,
        "RemoveMessageHistory": RemoveMessageHistory,
    }

    for attempt in range(config.MAX_RETRIES):
        try:
            while True:
                response = client.models.generate_content(
                    model=config.TOKEN_REDUCER_PLANER,
                    contents=chat, # type: ignore
                    config=types.GenerateContentConfig(
                        system_instruction=prompt.TOKEN_REDUCER_SYSTEM_INSTUNCTION,
                        temperature=0,
                        tools=list(function_map.values()),
                        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True, maximum_remote_calls=None),
                    ),
                )
                content = types.Content(role="user", parts=[])
                didentStop = False

                for part in response.candidates[0].content.parts: # type: ignore
                    if part.function_call:
                        didentStop = True
                        function_name = part.function_call.name
                        function = function_map.get(function_name or "")
                        if function:
                            try:
                                output = function(*part.function_call.args)
                                content.parts.append( # type: ignore
                                    types.Part(
                                        function_response=types.FunctionResponse(
                                            id=part.function_call.id,
                                            name=function_name,
                                            response={"output": output},
                                        )
                                    )
                                )
                            except Exception as e:
                                content.parts.append( # type: ignore
                                    types.Part(
                                        function_response=types.FunctionResponse(
                                            id=part.function_call.id,
                                            name=function_name,
                                            response={"error": e},
                                        )
                                    )
                                )
                        else:
                            content.parts.append( # type: ignore
                                types.Part(
                                    function_response=types.FunctionResponse(
                                        id=part.function_call.id,
                                        name=function_name,
                                        response={"error": f"Unknown Function: {function_name}"},
                                    )
                                )
                            )
                    if part.text:
                        didentStop = True
                chat = chat_history.for_summarizer()
                chat.append(response.candidates[0].content) # type: ignore
                chat.append(content) # type: ignore
                if not didentStop:
                    break
            return True
        except Exception as e:
            print(f"Attempt {attempt + 1} failed: {e}")
            if attempt < config.MAX_RETRIES - 1:
                time.sleep(attempt * config.RETRY_DELAY)
            else:
                print("Max retries reached. Failed to reduce token usage.")
                return False

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


# Flask Routes

@app.route('/favicon.ico')
def favicon():
    return redirect(url_for('static', filename='favicon.ico'), code=302)

@app.route('/')
def root():
    return render_template('index.html')

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
