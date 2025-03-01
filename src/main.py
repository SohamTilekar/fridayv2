import re
from flask import Flask, render_template, request, jsonify, redirect, url_for
from flask_socketio import SocketIO
from google import genai
from google.genai import types
import prompt
import config
import uuid
import PIL.Image
from io import BytesIO  # Import BytesIO
from typing import Literal, Optional
import json
import os
import base64
import time
import json

app = Flask("Friday")
socketio = SocketIO(app)

client = genai.Client(api_key=config.GOOGLE_API)

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

    def for_ai(self):
        if self.type.startswith("text/"):
            return f"\\nFile_name: {self.filename}\\nFile_Content: {self.content.decode('utf-8')}"  # Decode text files
        elif self.type.startswith("image/"):
            return PIL.Image.open(BytesIO(self.content))
        elif self.type.startswith("video/"):
            # Use cloud URI if available, otherwise upload
            x = False
            full_filename = f"{self.id}{os.path.splitext(self.filename)[1].replace('.', '--', 1)}" # Construct the full filename with extension
            try:
                client.files.get(name=full_filename)
                x = True
            except Exception as e:
                ...
            if x:
                return self.cloud_uri
            else:
                self.cloud_uri = client.files.upload(file=BytesIO(self.content), config={"display_name": self.filename, "mime_type": self.type, "name": full_filename})
                # Check whether the file is ready to be used.
                while self.cloud_uri.state.name == "PROCESSING":
                    time.sleep(1)
                    self.cloud_uri = client.files.get(name=self.cloud_uri.name)
                if self.cloud_uri.state.name == "FAILED":
                    raise ValueError(self.cloud_uri.state.name)
                return self.cloud_uri
        return None
    
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
    role: Literal["ai", "user"]
    content: str
    attachments: list[File]
    id: str

    def __init__(self, content: str, role: Literal["ai", "user"], attachments: Optional[list[File]] = None):
        self.content = content
        self.role = role
        self.id = str(uuid.uuid4())
        self.attachments = attachments if attachments is not None else []

    def for_ai(self) -> list[str]:
        content_str = f"{self.role}: {self.content}"
        ai_content: list = [content_str]
        for file in self.attachments:
            file_content = file.for_ai()
            if file_content:
                ai_content.append(file_content)
        return ai_content

    def jsonify(self) -> dict[str, str | Literal["ai", "user"] | list]:
        return {
            "role": self.role,
            "content": self.content,
            "id": self.id,
            "attachments": [file.jsonify() for file in self.attachments]
        }

    @staticmethod
    def from_jsonify(data: dict):
        attachments = [File.from_jsonify(file_data) for file_data in data.get('attachments', [])]
        return Message(data['content'], data['role'], attachments)

class ChatHistory:
    chat: list[Message] = []

    def append(self, msg: Message):
        self.chat.append(msg)
        socketio.emit("chat_update", self.jsonify())

    def delete(self, msg_id: str):
        """Deletes a message from the chat history."""
        original_length = len(self.chat)
        self.chat = [msg for msg in self.chat if msg.id != msg_id]
        if len(self.chat) < original_length:
            socketio.emit("chat_update", self.jsonify())
            return True
        return False

    def __len__(self):
        return len(self.chat)

    def to_str_list(self) -> list:
        result = []
        for msg_list in [msg.for_ai() for msg in self.chat]:
            if isinstance(msg_list, list):
                result.extend(msg_list)
            else:
                result.append(msg_list)
        return result

    def jsonify(self) -> list[dict[str, str | Literal["ai", "user"] | list]]:
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
    chat_history.append(Message("", "ai"))
    idx = len(chat_history) - 1
    try:
        response = client.models.generate_content_stream(
            model="gemini-2.0-flash",
            contents=chat_history.to_str_list(),
            config=types.GenerateContentConfig(
                system_instruction=prompt.SYSTEM_INSTUNCTION,
                temperature=0.25
            )
        )
        for content in response:
            if content.text:
                msg = chat_history.chat[idx]
                if not msg:
                    break
                msg.content += content.text
                socketio.emit("updated_msg", msg.jsonify())
    except Exception as e:
        msg = chat_history.chat[idx]
        msg.content = f"Error: {e}"
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
        else:
            print("Unsupported file type")

    completeChat(message, file_attachments)

@socketio.on("get_chat_history")
def handle_get_chat_history():
    socketio.emit("chat_update", chat_history.jsonify())

@socketio.on("delete_message")
def handle_delete_message(data):
    msg_id = data.get("message_id")
    if msg_id:
        if chat_history.delete(msg_id):
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
