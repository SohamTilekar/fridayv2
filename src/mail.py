# mail.py
import os.path
import json
import datetime
import time
import base64
from typing import Literal

import config
from rich import print
import utils
from global_shares import global_shares

# Gmail API imports
import google.auth.exceptions
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from email.utils import parsedate_to_datetime

# Notification related imports
from notification import EmailNotification, Content, notifications

# Gmail API scopes
SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.modify",
]


@utils.retry(
    exceptions=utils.network_errors, ignore_exceptions=utils.ignore_network_error
)
def get_gmail_service():
    """
    Authenticates and returns the Gmail API service.
    Handles token creation, refresh, and loading.
    """
    creds = None
    token_path = "token.json"

    # Load credentials from token file if it exists
    if os.path.exists(token_path):
        creds = Credentials.from_authorized_user_file(token_path, SCOPES)

    # Check if credentials are valid and refresh if needed
    if creds:
        if creds.valid:
            print("Token is valid.")
        elif creds.expired and creds.refresh_token:
            print("Token expired, attempting to refresh...")
            try:
                creds.refresh(Request())
                print("Token refreshed successfully.")
            except google.auth.exceptions.RefreshError:
                print(
                    "Token refresh failed. It might be revoked or invalid. Re-authentication required."
                )
                creds = None
        else:
            print("Token is invalid or revoked. Re-authentication required.")
            creds = None

    # If no valid credentials, authenticate and store the token
    if creds is None:
        flow = InstalledAppFlow.from_client_secrets_file("credentials.json", SCOPES)
        creds = flow.run_local_server(port=0)
        with open(token_path, "w") as token:
            token.write(creds.to_json())
        print("New authentication completed and token saved.")

    # Build and return the Gmail service
    service = build("gmail", "v1", credentials=creds)
    return service


def load_last_mail_checked():
    """
    Loads the last checked timestamp from a JSON file.
    If the file doesn't exist, returns the current time.
    """
    last_checked_file = config.AI_DIR / "mail_last_checked.json"
    if os.path.exists(last_checked_file):
        with open(last_checked_file, "r") as f:
            data = json.load(f)
            if "last_checked" in data:
                return datetime.datetime.fromisoformat(data["last_checked"])
    return datetime.datetime.now()  # Use current time if file doesn't exist


def save_last_mail_checked(timestamp):
    """
    Saves the last checked timestamp to a JSON file.
    """
    last_checked_file = config.AI_DIR / "mail_last_checked.json"
    with open(last_checked_file, "w") as f:
        json.dump({"last_checked": timestamp.isoformat()}, f)


@utils.retry(
    exceptions=utils.network_errors, ignore_exceptions=utils.ignore_network_error
)
def mark_as_read(message_id):
    """
    Marks the given message as read using the Gmail API.
    """
    global_shares["mail_service"].users().messages().modify(
        userId="me", id=message_id, body={"removeLabelIds": ["UNREAD"]}
    ).execute()


@utils.retry(
    exceptions=utils.network_errors, ignore_exceptions=utils.ignore_network_error
)
def check_emails(service, last_checked):
    """
    Checks for unread emails in the inbox after a specified timestamp.
    Extracts relevant information and creates EmailNotification objects.
    """
    date_string = int(last_checked.timestamp())
    query = f"is:unread after:{date_string}"
    results = (
        service.users()
        .messages()
        .list(userId="me", q=query, labelIds=["INBOX"])
        .execute()
    )
    messages = results.get("messages", [])

    if not messages:
        return  # No new messages found.

    for message in messages:
        msg = (
            service.users()
            .messages()
            .get(userId="me", id=message["id"], format="full")
            .execute()
        )

        # Extracting data from the email message
        headers = msg["payload"]["headers"]
        sender = next(
            (item["value"] for item in headers if item["name"] == "From"),
            "Unknown Sender",
        )
        subject = next(
            (item["value"] for item in headers if item["name"] == "Subject"),
            "No Subject",
        )
        date_header = next(
            (item["value"] for item in headers if item["name"] == "Date"), None
        )
        email_time = (
            parsedate_to_datetime(date_header)
            if date_header
            else datetime.datetime.now()
        )  # Parse date or use current time as fallback

        # Extract the body parts
        body_contents = []
        snipit_content = Content(text="Empty Body")  # Default snipit if body is empty
        try:
            payload = msg["payload"]
            if "parts" in payload:
                has_html = False
                for part in payload["parts"]:
                    print(part["mimeType"])
                    if part["mimeType"] == "text/html":
                        has_html = True
                        html_body = base64.urlsafe_b64decode(
                            part["body"]["data"]
                        ).decode()
                        body_contents.append(Content(type="html", html=html_body))
                        snipit_content = Content(
                            type="html",
                            html=(
                                html_body[:100] + "..."
                                if len(html_body) > 100
                                else html_body
                            ),
                        )
                        break  # Exit after processing the HTML part
                if not has_html:
                    for part in payload["parts"]:
                        if part["mimeType"] == "text/plain":
                            text_body = base64.urlsafe_b64decode(
                                part["body"]["data"]
                            ).decode()
                            body_contents.append(Content(type="text", text=text_body))
                            snipit_content = Content(
                                type="text",
                                text=(
                                    text_body[:100] + "..."
                                    if len(text_body) > 100
                                    else text_body
                                ),
                            )
                            break  # Exit after processing the text part
            elif (
                "body" in payload and "data" in payload["body"]
            ):  # Handling single part messages
                text_body = base64.urlsafe_b64decode(payload["body"]["data"]).decode()
                body_contents.append(Content(type="text", text=text_body))
                snipit_content = Content(
                    type="text",
                    text=text_body[:100] + "..." if len(text_body) > 100 else text_body,
                )
            else:
                body_contents.append(Content(type="text", text="Empty Body"))

        except KeyError:
            body_contents.append(Content(type="text", text="Error decoding body"))

        # Determine the category and severity of the email
        category = get_email_category(service, message["id"])
        severity = map_category_to_severity(category)

        # Create a EmailNotification object and add it to the notifications list
        notification = EmailNotification(
            id=message["id"],
            sender=sender,
            subject=subject,
            body=body_contents,
            snipit=snipit_content,
            sevarity=severity,
            reminder=False,
            personal=True,
            time=email_time,  # Use parsed email time
        )
        notifications.append(notification)


@utils.retry(
    exceptions=utils.network_errors, ignore_exceptions=utils.ignore_network_error
)
def get_email_category(service, message_id: str) -> Literal[
    "CATEGORY_PERSONAL",
    "CATEGORY_SOCIAL",
    "CATEGORY_PROMOTIONS",
    "CATEGORY_UPDATES",
    "CATEGORY_FORUMS",
    "Other",
]:
    """
    Gets the category of an email directly from Gmail API labels.
    """
    msg = (
        service.users()
        .messages()
        .get(userId="me", id=message_id, format="minimal")
        .execute()
    )
    labels = msg.get("labelIds", [])

    for label in labels:
        if label in [
            "CATEGORY_PERSONAL",
            "CATEGORY_SOCIAL",
            "CATEGORY_PROMOTIONS",
            "CATEGORY_UPDATES",
            "CATEGORY_FORUMS",
        ]:
            return label
    return "Other"


def map_category_to_severity(category: str) -> Literal["Low", "Mid", "High"]:
    """
    Maps email category to a severity level.
    """
    if category == "CATEGORY_PERSONAL":
        return "High"
    elif category == "CATEGORY_UPDATES":
        return "Mid"
    else:
        return "Low"


@utils.retry(
    exceptions=utils.network_errors, ignore_exceptions=utils.ignore_network_error
)
def start_checking_mail():
    """
    Starts the main loop for checking emails.
    Authenticates the Gmail service, loads the last checked timestamp,
    and continuously checks for new emails.
    """
    service = get_gmail_service()
    global_shares["mail_service"] = service
    if service:
        last_checked = load_last_mail_checked()
        while True:
            check_emails(service, last_checked)
            last_checked = datetime.datetime.now()  # Update the last checked timestamp
            save_last_mail_checked(last_checked)
            time.sleep(20)
