import re
from rich import print
import rich
from flask import Flask, render_template, request, jsonify, redirect, url_for
from flask_socketio import SocketIO
from google import genai
from google.genai import types
import rich.bar
import prompt
import config
import uuid
from io import BytesIO  # Import BytesIO
from typing import Literal, Optional
import json
import os
import base64
import time
import datetime

app = Flask("Friday")
socketio = SocketIO(app)

client = genai.Client(api_key=config.GOOGLE_API)

google_search_tool = types.Tool(
    google_search = types.GoogleSearch()
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
        self.id = str(uuid.uuid4()) if id is None else id  # Use the new method to generate a valid ID
        self.cloud_uri = cloud_uri
    
    def delete(self):
        if self.cloud_uri and self.is_expiration_valid(self.cloud_uri.expiration_time):
            client.files.delete(name=self.cloud_uri.name) # type: ignore

    @staticmethod
    def _generate_valid_video_file_id():
        """Generates a valid ID that conforms to the naming requirements."""
        # Generate a UUID, convert to string, make lowercase, and replace invalid characters with dashes.
        base_id = str(uuid.uuid4()).lower()[:35]
        # Ensure the ID doesn't start or end with a dash.  Add a prefix if needed.
        valid_id = re.sub(r'^[^a-z0-9]+|[^a-z0-9]+$', '', base_id) # Remove leading/trailing non-alphanumeric characters
        if not valid_id:
            valid_id = "file-id" # Default ID if the UUID generates an empty string after cleaning.
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
            return types.Part.from_text(text=f"\\nFile_name: {self.filename}\\nFile_Content: {self.content.decode('utf-8')}")  # Decode text files
        elif self.type.startswith(("image/", "video/", "application/pdf")):
            # Use cloud URI if available, otherwise upload
            if self.cloud_uri and self.is_expiration_valid(self.cloud_uri.expiration_time):
                return self.cloud_uri # type: ignore
            
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
                    self.cloud_uri = client.files.upload(file=BytesIO(self.content), config={"display_name": self.filename, "mime_type": self.type})
                    # Check whether the file is ready to be used.
                    while self.cloud_uri.state.name == "PROCESSING":
                        time.sleep(1)
                        self.cloud_uri = client.files.get(name=self.cloud_uri.name)
                    if self.cloud_uri.state.name == "FAILED":
                        raise ValueError(self.cloud_uri.state.name)
                    msg.content = ""
                    socketio.emit("updated_msg", msg.jsonify())
                    return self.cloud_uri # type: ignore
                except Exception:
                    if attempt < config.MAX_RETRIES - 1:
                        time.sleep(config.RETRY_DELAY)
                    else:
                        raise  # Re-raise the exception to be caught in completeChat
        raise ValueError(f"Unsported File Type: {self.type} of file {self.filename}")
    
    def jsonify(self):
        return {
            "type": self.type,
            "filename": self.filename,
            "content": base64.b64encode(self.content).decode('utf-8', errors='ignore'),  # Base64 encode
            "id": self.id
        }

    @staticmethod
    def from_jsonify(data: dict):
        content = base64.b64decode(data['content'])
        return File(content, data['type'], data['filename'], None, data['id'])

class Message:
    role: Literal["model", "user"]
    content: str
    time_stamp: datetime.datetime
    attachments: list[File]
    id: str

    def __init__(self, content: str, role: Literal["model", "user"], attachments: Optional[list[File]] = None, time_stamp: Optional[datetime.datetime] = None):
        self.time_stamp = time_stamp if time_stamp else datetime.datetime.now()
        self.content = content
        self.role = role
        self.id = str(uuid.uuid4())
        self.attachments = attachments if attachments is not None else []

    def delete(self):
        for file in self.attachments:
            file.delete()

    def for_ai(self, msg: "Message") -> types.Content:
        ai_content: list[types.Part] = []
        for file in self.attachments:
            ai_content.append(file.for_ai(msg))
        ai_content.append(types.Part.from_text(text=self.time_stamp.strftime("%H:%M")))
        if self.content:
            ai_content.append(types.Part.from_text(text=self.content))
        return types.Content(parts=ai_content, role=self.role)

    def jsonify(self) -> dict[str, str | Literal["model", "user"] | list]:
        return {
            "role": self.role,
            "content": self.content,
            "id": self.id,
            "time_stamp": self.time_stamp.isoformat(),  # Convert datetime to ISO format string
            "attachments": [file.jsonify() for file in self.attachments]
        }

    @staticmethod
    def from_jsonify(data: dict):
        attachments = [File.from_jsonify(file_data) for file_data in data.get('attachments', [])]
        return Message(data['content'], data['role'], attachments, datetime.datetime.fromisoformat(data["time_stamp"]))

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

def completeChat(message: str, files: Optional[list[File]] = None):
    if files is None:
        files = []
    if message or files:  # Only append if there's content or files
        chat_history.append(Message(message, "user", files))

    # Append a placeholder for the AI reply
    chat_history.append(Message("", "model"))
    idx = len(chat_history) - 1
    msg = chat_history.chat[idx]
    for attempt in range(config.MAX_RETRIES):
        try:
            x = 0
            while (True):
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
                for content in response:
                    print("-----------------------")
                    print("content=", content)
                    print("-----------------------")
                    if content.text:
                        msg.content += content.text
                        socketio.emit("updated_msg", msg.jsonify())
                tokens: int = client.models.count_tokens(model="gemini-2.0-flash", contents=msg.content).total_tokens or 0
                if tokens >= 8150*x:
                    continue # Recalling AI cz max output tokens are passed
                break
            msg.time_stamp = datetime.datetime.now()
            break
        except Exception as e:
            if attempt < config.MAX_RETRIES - 1:
                time.sleep(config.RETRY_DELAY)
            else:
                error_message = f"Failed to generate response after multiple retries: {str(e)}"
                msg.content = error_message
                socketio.emit("updated_msg", msg.jsonify())

@app.route('/favicon.ico')
def favicon():
    return redirect(url_for('static', filename='favicon.ico'), code=302)

# Render the main chat frontend
@app.route('/')
def root():
    return render_template('index.html')

videos: dict[str, tuple[dict[int, str], bool]] = {} # ID & [its chuncks with their idx & is fully uploded (true if video is fully uploded otherwise false)]

@socketio.on("start_upload_video")
def start_upload_video(id: str):
    videos[id] = ({}, False)

@socketio.on("upload_video_chunck")
def upload_video_chunck(data: dict[str, str | int]):
    id: str = data["id"] # type: ignore
    chunck: str = data["chunck"] # type: ignore
    idx: int = data["idx"] # type: ignore
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
            while(not videos.get(id)):
                time.sleep(0.1)
            while(not videos[id][1]):
                time.sleep(0.2)
            vid = videos[id][0]
            x = 0
            content: str = ""
            while(vid.get(x) is not None):
                content += vid[x]
                x += 1
            decoded_content = base64.b64decode(content)
            file_attachments.append(File(decoded_content, file_type, filename, None, File._generate_valid_video_file_id()))
            del videos[id]

    completeChat(message, file_attachments)

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
        socketio.run(app, host='127.0.0.1', port=5000, debug=True, use_reloader=False)
    finally:
        chat_history_file = os.path.join(config.DATA_DIR, "chat_history.json")
        chat_history.save_to_json(chat_history_file)
        print("Chat history saved.")
