# notification.py
import json
import datetime
from rich import print
from typing import Any, Literal, Optional, List
from global_shares import global_shares

import uuid

type ContentType = Literal["text", "html", "image"]

class Content():
    type: ContentType = "text"
    text: Optional[str] = None
    html: Optional[str] = None
    img: Optional[str] = None # base64 encoded image

    def __init__(self, type: ContentType = "text", text: Optional[str] = None, html: Optional[str] = None, img: Optional[str] = None):
        self.type = type
        self.text = text
        self.html = html
        self.img = img

    def jsonify(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "text": self.text,
            "html": self.html,
            "img": self.img,
        }

    @staticmethod
    def from_jsonify(data: dict[str, Any]) -> "Content":
        return Content(
            type=data.get("type", "text"),
            text=data.get("text"),
            html=data.get("html"),
            img=data.get("img"),
        )

NotificationType = Literal["Mail", "Reminder", "General"]

class Notification():
    id: str
    type: NotificationType = "General"
    content: list[Content]
    snipit: Content
    time: datetime.datetime
    sevarity: Literal["Low", "Mid", "High"] = "Low"
    reminder: bool
    personal: bool = False

    def __init__(self, notification_type: NotificationType = "General", id: Optional[str] = None, content: Optional[list[Content]] = None, snipit: Optional[Content] = None, time: Optional[datetime.datetime] = None, sevarity: Literal["Low", "Mid", "High"] = "Low", reminder: bool = False, personal: bool = False):
        self.id = id if id else str(uuid.uuid4())
        self.type = notification_type
        self.content = content if content is not None else []
        self.snipit = snipit if snipit else Content()
        self.time = time if time else datetime.datetime.now()
        self.sevarity = sevarity
        self.reminder = reminder
        self.personal = personal

    def jsonify(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "type": self.type,
            "content": [c.jsonify() for c in self.content],
            "snipit": self.snipit.jsonify(),
            "time": self.time.isoformat(),
            "sevarity": self.sevarity,
            "reminder": self.reminder,
            "personal": self.personal,
        }

    @staticmethod
    def from_jsonify(data: dict[str, Any]) -> "Notification":
        return Notification(
            notification_type=data.get("type", "General"),
            id=data["id"],
            content=[Content.from_jsonify(c) for c in data.get("content", [])],
            snipit=Content.from_jsonify(data["snipit"]) if data.get("snipit") else Content(),
            time=datetime.datetime.fromisoformat(data["time"]),
            sevarity=data["sevarity"],
            reminder=data["reminder"],
            personal=data["personal"],
        )

class EmailNotification(Notification):
    type: NotificationType = "Mail"
    subject: str
    sender: str
    body: List[Content]

    def __init__(self, id: Optional[str] = None, subject: Optional[str] = None, sender: Optional[str] = None, body: Optional[List[Content]] = None, snipit: Optional[Content] = None, time: Optional[datetime.datetime] = None, sevarity: Literal["Low", "Mid", "High"] = "Low", reminder: bool = False, personal: bool = False):
        super().__init__(notification_type="Mail", id=id, snipit=snipit, time=time, sevarity=sevarity, reminder=reminder, personal=personal)
        self.subject = subject if subject else "No Subject"
        self.sender = sender if sender else "Unknown Sender"
        self.body = body if body else []

    def jsonify(self) -> dict[str, Any]:
        base_json = super().jsonify()
        base_json.update({
            "subject": self.subject,
            "sender": self.sender,
            "body": [c.jsonify() for c in self.body],
        })
        return base_json

    @staticmethod
    def from_jsonify(data: dict[str, Any]) -> "EmailNotification":
        base_notification = Notification.from_jsonify(data)
        return EmailNotification(
            id=base_notification.id,
            snipit=base_notification.snipit,
            time=base_notification.time,
            sevarity=base_notification.sevarity,
            reminder=base_notification.reminder,
            personal=base_notification.personal,
            subject=data.get("subject", "No Subject"),
            sender=data.get("sender", "Unknown Sender"),
            body=[Content.from_jsonify(c) for c in data.get("body", [])],
        )


class Notifications():
    notifications: list[Notification] = []

    def __init__(self, notifications: Optional[list[Notification]] = None):
        self.notifications = notifications if notifications else []

    def append(self, notification: Notification):
        global_shares["socketio"].emit("add_notification", notification.jsonify())
        self.notifications.append(notification)

    def delete(self, id: str):
        for idx, notification in enumerate(self.notifications):
            if notification.id == id:
                if notification.type == "Mail":
                    import mail
                    mail.mark_as_read(notification.id)
                del self.notifications[idx]

    def save_to_json(self, filepath: str):
        """Saves the notifications to a JSON file."""
        data = [notification.jsonify() for notification in self.notifications]
        with open(filepath, 'w') as f:
            json.dump(data, f, indent=4)

    def load_from_json(self, filepath) -> None:
        try:
            with open(filepath, 'r') as f:
                data: list[dict[str, Any]] = json.load(f)
                self.notifications = []
                for item in data:
                    notif_type = item.get("type")
                    if notif_type == "Mail":
                        self.notifications.append(EmailNotification.from_jsonify(item))
                    else: # Fallback to default Notification for unknown types
                        self.notifications.append(Notification.from_jsonify(item))
        except FileNotFoundError:
            print("Notification file not found. Starting with an empty notifications list.")
        except json.JSONDecodeError:
            print("Error decoding notification file. Starting with an empty notifications list.")

notifications: Notifications = Notifications()
