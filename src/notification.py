# notification.py
import json
import datetime
from rich import print
from typing import Any, Literal, Optional
from global_shares import global_shares
import uuid

ContentType = Literal["text", "html", "image"]


class Content:
    """
    Represents the content of a notification.

    Attributes:
        type (ContentType): The type of the content (text, html, or image).
        text (Optional[str]): The text content, if type is "text".
        html (Optional[str]): The HTML content, if type is "html".
        img (Optional[str]): The base64 encoded image data, if type is "image".
    """

    type: ContentType  # type of the Content
    text: Optional[str]  # if content is text
    html: Optional[str]  # if content is html
    img: Optional[str]  # base64 encoded image

    def __init__(
        self,
        type: ContentType = "text",
        text: Optional[str] = None,
        html: Optional[str] = None,
        img: Optional[str] = None,
    ):
        """Initializes a Content object."""
        self.type = type
        self.text = text
        self.html = html
        self.img = img

    def jsonify(self) -> dict[str, Any]:
        """
        Converts the Content object to a JSON-serializable dictionary.
        """
        return {
            "type": self.type,
            "text": self.text,
            "html": self.html,
            "img": self.img,
        }

    @staticmethod
    def from_jsonify(data: dict[str, Any]) -> "Content":
        """
        Creates a Content object from a JSON-like dictionary.
        """
        return Content(**data)


NotificationType = Literal["Mail", "Reminder", "General"]


class Notification:
    """
    Represents a base notification.

    Attributes:
        id (str): Unique identifier for the notification.
        type (NotificationType): Type of the notification (Mail, Reminder, or General).
        content (list[Content]): A list of Content objects representing the full content.
        snipit (Content): A short summary or preview of the content.
        time (datetime.datetime): The timestamp of the notification.
        sevarity (Literal["Low", "Mid", "High"]): Importance level.
        reminder (bool): Indicates if this is a reminder notification.
        personal (bool): Indicates if the content contains personal information.
    """

    id: str  # id of notification
    type: NotificationType
    content: list[Content]  # complete content
    snipit: Content  # content snipit to display
    time: datetime.datetime  # time of the notification
    sevarity: Literal["Low", "Mid", "High"]  # importance of the notification
    reminder: bool  # is notification reminder
    personal: bool  # is notification content personal

    def __init__(
        self,
        notification_type: NotificationType = "General",
        id: Optional[str] = None,
        content: Optional[list[Content]] = None,
        snipit: Optional[Content] = None,
        time: Optional[datetime.datetime] = None,
        sevarity: Literal["Low", "Mid", "High"] = "Low",
        reminder: bool = False,
        personal: bool = False,
    ):
        """Initializes a Notification object."""
        self.id = id if id else str(uuid.uuid4())
        self.type = notification_type
        self.content = content if content is not None else []
        self.snipit = snipit if snipit else Content()
        self.time = time if time else datetime.datetime.now()
        self.sevarity = sevarity
        self.reminder = reminder
        self.personal = personal

    def jsonify(self) -> dict[str, Any]:
        """
        Converts the Notification object to a JSON-serializable dictionary.
        """
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
        """
        Creates a Notification object from a JSON-like dictionary.
        """
        return Notification(
            notification_type=data.get("type", "General"),
            id=data["id"],
            content=[Content.from_jsonify(c) for c in data["content"]],
            snipit=(
                Content.from_jsonify(data["snipit"]) if data["snipit"] else Content()
            ),
            time=datetime.datetime.fromisoformat(data["time"]),
            sevarity=data["sevarity"],
            reminder=data["reminder"],
            personal=data["personal"],
        )


class EmailNotification(Notification):
    """
    Represents an email notification, extending the base Notification class.

    Attributes:
        subject (str): The subject line of the email.
        sender (str): The email address of the sender.
        body (list[Content]): The main content of the email.
    """

    subject: str  # subject of the email
    sender: str  # email address of the sender of the email
    body: list[Content]  # body of the mail

    def __init__(
        self,
        id: Optional[str] = None,
        subject: Optional[str] = None,
        sender: Optional[str] = None,
        body: Optional[list[Content]] = None,
        snipit: Optional[Content] = None,
        time: Optional[datetime.datetime] = None,
        sevarity: Literal["Low", "Mid", "High"] = "Low",
        reminder: bool = False,
        personal: bool = False,
    ):
        """Initializes an EmailNotification object."""
        super().__init__(
            notification_type="Mail",
            id=id,
            snipit=snipit,
            time=time,
            sevarity=sevarity,
            reminder=reminder,
            personal=personal,
        )
        self.subject = subject if subject else "No Subject"
        self.sender = sender if sender else "Unknown Sender"
        self.body = body if body else []

    def jsonify(self) -> dict[str, Any]:
        """
        Converts the EmailNotification object to a JSON-serializable dictionary.
        """
        base_json = super().jsonify()
        base_json.update(
            {
                "subject": self.subject,
                "sender": self.sender,
                "body": [c.jsonify() for c in self.body],
            }
        )
        return base_json

    @staticmethod
    def from_jsonify(data: dict[str, Any]) -> "EmailNotification":
        """
        Creates an EmailNotification object from a JSON-like dictionary.
        """
        base_notification = Notification.from_jsonify(data)
        return EmailNotification(
            id=base_notification.id,
            snipit=base_notification.snipit,
            time=base_notification.time,
            sevarity=base_notification.sevarity,
            reminder=base_notification.reminder,
            personal=base_notification.personal,
            subject=data["subject"],
            sender=data["sender"],
            body=[Content.from_jsonify(c) for c in data.get("body", [])],
        )


class Notifications:
    """
    Manages a list of notifications.

    Attributes:
        notifications (list[Notification]): The list of Notification objects.
    """

    _instance: Optional["Notifications"] = None

    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            cls._instance = super().__new__(cls, *args, **kwargs)
            cls._instance.notifications = []
        return cls._instance

    def __init__(self, notifications: Optional[list[Notification]] = None):
        """Initializes a Notifications object."""
        if not hasattr(self, "notifications"):  # Only initialize once
            self.notifications = notifications if notifications else []

    def append(self, notification: Notification):
        """
        Appends a notification to the list and emits a SocketIO event.
        """
        global_shares["socketio"].emit("add_notification", notification.jsonify())
        self.notifications.append(notification)

    def delete(self, id: str):
        """
        Deletes a notification from the list by its ID.
        If the notification is an email, it also marks it as read.
        """
        for idx, notification in enumerate(self.notifications):
            if notification.id == id:
                if notification.type == "Mail":
                    import mail
                    mail.mark_as_read(notification.id)
                del self.notifications[idx]

    def save_to_json(self, filepath: str):
        """Saves the notifications to a JSON file."""
        data = [notification.jsonify() for notification in self.notifications]
        with open(filepath, "w") as f:
            json.dump(data, f, indent=4)

    def load_from_json(self, filepath) -> None:
        """Loads notifications from a JSON file."""
        try:
            with open(filepath, "r") as f:
                data: list[dict[str, Any]] = json.load(f)
                self.notifications = []
                for item in data:
                    notif_type = item.get("type")
                    if notif_type == "Mail":
                        self.notifications.append(EmailNotification.from_jsonify(item))
                    else:  # Fallback to default Notification for unknown types
                        self.notifications.append(Notification.from_jsonify(item))
        except FileNotFoundError:
            print(
                "Notification file not found. Starting with an empty notifications list."
            )
        except json.JSONDecodeError:
            print(
                "Error decoding notification file. Starting with an empty notifications list."
            )


# Global instance to store all notifications
notifications: Notifications = Notifications()
