# mail.py
import os.path
import json
import datetime
import time
import base64
from typing import Literal

import httplib2
import config
import ssl
from rich import print
import utils
from global_shares import global_shares

import google.auth.exceptions
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from email.utils import parsedate_to_datetime

from notification import EmailNotification, Content, notifications

# If modifying these scopes, delete the file token.json.
SCOPES = ['https://www.googleapis.com/auth/gmail.readonly', 'https://www.googleapis.com/auth/gmail.modify']

@utils.retry(exceptions=(HttpError, TimeoutError, ssl.SSLEOFError, ssl.SSLError, httplib2.error.ServerNotFoundError), max_retries=float("inf"))
def get_gmail_service():
    """Authenticates and returns the Gmail API service."""
    creds = None
    if os.path.exists('token.json'):
        creds = Credentials.from_authorized_user_file('token.json', SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                'credentials.json', SCOPES)
            creds = flow.run_local_server(port=0)
        with open('token.json', 'w') as token:
            token.write(creds.to_json())

    service = build('gmail', 'v1', credentials=creds)
    return service

def load_last_mail_checked():
    """Loads the last checked timestamp from a JSON file.
    If the file doesn't exist, returns the current time.
    """
    if os.path.exists(config.AI_DIR/'mail_last_checked.json'):
        with open(config.AI_DIR/'mail_last_checked.json', 'r') as f:
            data = json.load(f)
            if 'last_checked' in data:
                return datetime.datetime.fromisoformat(data['last_checked'])
    return datetime.datetime.now()  # Use current time if file doesn't exist

def save_last_mail_checked(timestamp):
    """Saves the last checked timestamp to a JSON file."""
    with open(config.AI_DIR/'mail_last_checked.json', 'w') as f:
        json.dump({'last_checked': timestamp.isoformat()}, f)

@utils.retry(exceptions=(HttpError, TimeoutError, ssl.SSLEOFError, ssl.SSLError, httplib2.error.ServerNotFoundError), max_retries=float("inf"))
def mark_as_read(message_id):
    """Marks the given message as read."""
    global_shares["mail_service"].users().messages().modify(userId='me', id=message_id, body={'removeLabelIds': ['UNREAD']}).execute()

@utils.retry(exceptions=(HttpError, TimeoutError, ssl.SSLEOFError, ssl.SSLError, httplib2.error.ServerNotFoundError, ), max_retries=float("inf"))
def check_emails(service, last_checked):
    date_string = int(last_checked.timestamp())
    query = f'is:unread after:{date_string}'
    results = service.users().messages().list(userId='me', q=query, labelIds=['INBOX']).execute()
    messages = results.get('messages', [])

    if not messages:
        return # No new messages found.

    for message in messages:
        msg = service.users().messages().get(userId='me', id=message['id'], format='full').execute()

        # Extracting data
        headers = msg['payload']['headers']
        sender = next((item['value'] for item in headers if item["name"] == "From"), "Unknown Sender")
        subject = next((item['value'] for item in headers if item["name"] == "Subject"), "No Subject")
        date_header = next((item['value'] for item in headers if item["name"] == "Date"), None)
        email_time = parsedate_to_datetime(date_header) if date_header else datetime.datetime.now() # Parse date or use current time as fallback


        # Extract the body parts
        body_contents = []
        snipit_content = Content(text="Empty Body") # Default snipit if body is empty
        try:
            payload = msg['payload']
            if 'parts' in payload:
                has_html = False
                for part in payload['parts']:
                    print(part['mimeType'])
                    if part['mimeType'] == 'text/html':
                        has_html = True
                        html_body = base64.urlsafe_b64decode(part['body']['data']).decode()
                        body_contents.append(Content(type="html", html=html_body))
                        snipit_content = Content(type="html", html=html_body[:100] + "..." if len(html_body) > 100 else html_body)
                        break # Exit after processing the HTML part
                if not has_html:
                    for part in payload['parts']:
                        if part['mimeType'] == 'text/plain':
                            text_body = base64.urlsafe_b64decode(part['body']['data']).decode()
                            body_contents.append(Content(type="text", text=text_body))
                            snipit_content = Content(type="text", text=text_body[:100] + "..." if len(text_body) > 100 else text_body)
                            break # Exit after processing the text part
            elif 'body' in payload and 'data' in payload['body']: # Handling single part messages
                text_body = base64.urlsafe_b64decode(payload['body']['data']).decode()
                body_contents.append(Content(type="text", text=text_body))
                snipit_content = Content(type="text", text=text_body[:100] + "..." if len(text_body) > 100 else text_body)
            else:
                body_contents.append(Content(type="text", text="Empty Body"))

        except KeyError:
            body_contents.append(Content(type="text", text="Error decoding body"))
        category = get_email_category(service, message['id'])
        severity = map_category_to_severity(category)

        # Create a EmailNotification object
        notification = EmailNotification(
            id=message['id'],
            sender=sender,
            subject=subject,
            body=body_contents,
            snipit=snipit_content,
            sevarity=severity,
            reminder=False,
            personal=True,
            time=email_time # Use parsed email time
        )
        notifications.append(notification) # Use notifications instead of noti.notifications

@utils.retry(exceptions=(HttpError, TimeoutError, ssl.SSLEOFError, ssl.SSLError, httplib2.error.ServerNotFoundError), max_retries=float("inf"))
def get_email_category(service, message_id: str) -> Literal["CATEGORY_PERSONAL", "CATEGORY_SOCIAL", "CATEGORY_PROMOTIONS", "CATEGORY_UPDATES", "CATEGORY_FORUMS", "Other"]:
    """
    Gets the category of an email directly from Gmail API labels.
    """
    try:
        msg = service.users().messages().get(userId='me', id=message_id, format='minimal').execute()
        labels = msg.get('labelIds', [])

        for label in labels:
            if label in ["CATEGORY_PERSONAL", "CATEGORY_SOCIAL", "CATEGORY_PROMOTIONS", "CATEGORY_UPDATES", "CATEGORY_FORUMS"]:
                return label
        return "Other"
    except HttpError as e:
        print("Error Occured: ", e)
        return "Other"

def map_category_to_severity(category: str) -> Literal["Low", "Mid", "High"]:
    """Maps email category to a severity level."""
    if category == "CATEGORY_PERSONAL":
        return "High"
    elif category == "CATEGORY_UPDATES":
        return "Mid"
    else:
        return "Low"

@utils.retry(exceptions=(HttpError, TimeoutError, ssl.SSLEOFError, ssl.SSLError, httplib2.error.ServerNotFoundError, google.auth.exceptions.TransportError), max_retries=float("inf"))
def start_checking_mail():
    service = get_gmail_service()
    global_shares['mail_service'] = service
    if service:
        last_checked = load_last_mail_checked()
        while True:
            check_emails(service, last_checked)
            last_checked = datetime.datetime.now()  # Update the last checked timestamp
            save_last_mail_checked(last_checked)
            time.sleep(60)  # Check every 60 seconds

# def list_labels():
#     # Initialize the Gmail API client
#     creds = Credentials.from_authorized_user_file('token.json')
#     service = build('gmail', 'v1', credentials=creds)

#     # List all labels in the user's mailbox
#     response = service.users().labels().list(userId='me').execute()
#     labels = response.get('labels', [])

#     # Print the labels
#     for label in labels:
#         print(f"Label ID: {label['id']}, Name: {label['name']}, Type: {label['type']}")

# list_labels()
