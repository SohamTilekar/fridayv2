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
from typing import Any, Literal, Optional
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
    content: bytes
    filename: str
    id: str
    cloud_uri: Optional[types.File] = None  # URI of the file in the cloud

    def __init__(self, content: bytes, type: str, filename: str, cloud_uri: Optional[types.File] = None, id: Optional[str] = None):
        self.content = content
        self.type = type
        self.filename = filename
        # Use the new method to generate a valid ID
        self.id = str(uuid.uuid4()) if id is None else id
        self.cloud_uri = cloud_uri

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

    def for_ai(self, msg: "Message") -> types.Part:
        if self.type.startswith("text/"):
            # Decode text files
            return types.Part.from_text(text=f"\\nFile_name: {self.filename}\\nFile_Content: {self.content.decode('utf-8')}")
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
                    socketio.emit("updated_msg", msg.jsonify())
                    self.cloud_uri = client.files.upload(file=BytesIO(self.content), config={
                                                         "display_name": self.filename, "mime_type": self.type})
                    # Check whether the file is ready to be used.
                    while self.cloud_uri.state.name == "PROCESSING":
                        time.sleep(1)
                        self.cloud_uri = client.files.get(
                            name=self.cloud_uri.name)
                    if self.cloud_uri.state.name == "FAILED":
                        raise ValueError(self.cloud_uri.state.name)
                    msg.content = ""
                    socketio.emit("updated_msg", msg.jsonify())
                    return self.cloud_uri  # type: ignore
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
            # Base64 encode
            "content": base64.b64encode(self.content).decode('utf-8', errors='ignore'),
            "id": self.id
        }

    @staticmethod
    def from_jsonify(data: dict):
        content = base64.b64decode(data['content'])
        return File(content, data['type'], data['filename'], None, data['id'])


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
                                 [GroundingSupport.from_jsonify(sup) for sup in data["grounding_supports"]],
                                 data["first_offset"],
                                 data.get("rendered_content", ""))


class Message:
    role: Literal["model", "user"]
    content: str
    time_stamp: datetime.datetime
    attachments: list[File]
    grounding_metadata: GroundingMetaData
    id: str

    def __init__(self, content: str, role: Literal["model", "user"], grounding_metadata: Optional[GroundingMetaData] = None, attachments: Optional[list[File]] = None, time_stamp: Optional[datetime.datetime] = None):
        self.time_stamp = time_stamp if time_stamp else datetime.datetime.now()
        self.content = content
        self.role = role
        self.id = str(uuid.uuid4())
        self.attachments = attachments if attachments is not None else []
        self.grounding_metadata = grounding_metadata if grounding_metadata else GroundingMetaData([
        ], [])

    def delete(self):
        for file in self.attachments:
            file.delete()

    def for_ai(self, msg: "Message") -> types.Content:
        ai_content: list[types.Part] = []
        for file in self.attachments:
            ai_content.append(file.for_ai(msg))
        ai_content.append(types.Part.from_text(
            text=self.time_stamp.strftime("%H:%M")))
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
            "attachments": [file.jsonify() for file in self.attachments]
        }

    @staticmethod
    def from_jsonify(data: dict):
        attachments = [File.from_jsonify(file_data)
                       for file_data in data.get('attachments', [])]
        return Message(data['content'], data['role'], GroundingMetaData.from_jsonify(data["grounding_metadata"]), attachments, datetime.datetime.fromisoformat(data["time_stamp"]))


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

    def for_ai(self, msg: Message) -> types.ContentListUnion:
        result: types.ContentListUnion = []
        for msg in self.chat:
            result.append(msg.for_ai(msg))
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
                    msg.grounding_metadata.grounding_chuncks.append((chunk.web.title, chunk.web.uri))  # type: ignore

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
            continue

        if first:
            msg.grounding_metadata.first_offset = start_index - support.segment.start_index  # type: ignore
            first = False

        msg.grounding_metadata.grounding_supports.append(
            GroundingSupport(support.grounding_chunk_indices, {  # type: ignore
                "text": support.segment.text,  # type: ignore
                "start_index": start_index,
                "end_index": start_index + len(support.segment.text)  # type: ignore
            })  # type: ignore
        )
    update_chat_with_response(msg)


def handle_generation_failure(msg: Message, error: Exception):
    """
    Handles the failure to generate a response from the AI model.
    """
    error_message = f"Failed to generate response after multiple retries: {str(error)}"
    msg.content = error_message
    update_chat_with_response(msg)


def update_chat_with_response(msg: Message):
    """
    Updates the chat history and emits the updated message.
    """
    socketio.emit("updated_msg", msg.jsonify())

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
