# reminder.py
import pickle
import time
import schedule
import config
from typing import Literal, List
import os
import datetime

from notification import Notification, Content, notifications

class Reminder:
    message: str
    once: bool
    skip_next: bool
    re_remind: bool
    id: int

    def __init__(self, message: str, once: bool) -> None:
        self.message = message
        self.once = once
        self.skip_next = False
        self.re_remind = False
        self.id = hash(self) # Generate ID here

    def __call__(self):
        if self.skip_next:
            self.skip_next = False
            return

        # Create a Notification object
        notification = Notification(
            notification_type="Reminder",
            snipit=Content(text=self.message[:100] + "..." if len(self.message) > 100 else self.message),
            time=datetime.datetime.now(),
            sevarity="Mid", # Or "Low" or "High" as appropriate
            reminder=True,
            personal=True,
        )
        notification.content = [Content(text=self.message)]

        notifications.append(notification)

        if self.once:
            return schedule.CancelJob

# Function to save the schedule jobs to a file
def save_jobs() -> None:
    """
    Save the scheduled jobs to a file using pickle.
    """
    with open(config.AI_DIR/"reminders.pkl", "wb") as f:
        pickle.dump(schedule.default_scheduler, f)


# Function to load the schedule jobs from a file
def load_jobs() -> None:
    """
    Load the scheduled jobs from a file using pickle, if it exists.
    """
    if os.path.exists(config.AI_DIR/"reminders.pkl"):
        with open(config.AI_DIR/"reminders.pkl", "rb") as f:
            schedule.default_scheduler = pickle.load(f)


# Function to run the reminders
def run_reminders() -> None:
    """
    Function to keep running the scheduled reminders and save them on exit.
    """
    load_jobs()  # Load reminders on startup

    while True:
        schedule.run_pending()
        time.sleep(5)


def get_reminders() -> str:
    """
    Get the list of scheduled reminders in a clean, human-readable format.

    Returns:
    - A list of strings, each containing the formatted reminder details.
    """
    reminders = "Reminders:\n"

    for job in schedule.get_jobs():
        once = "Yes" if "once" in job.tags else "No"

        # Skip "Last Run" if the job is scheduled to run once
        last_run = (
            job.last_run.strftime("%Y-%m-%d %H:%M:%S")
            if job.last_run and once == "No"
            else ""
        )
        frequency = ""

        # Handling different scheduling scenarios
        if job.unit == "seconds":
            frequency = f"Runs every {job.interval} seconds"
        elif job.unit == "minutes":
            frequency = f"Runs every {job.interval} minutes"
        elif job.unit == "hours":
            frequency = f"Runs every {job.interval} hours"
        elif job.unit == "days" and job.at_time:
            frequency = f"Runs every day at {job.at_time.strftime('%H:%M:%S')}"
        elif job.unit == "days":
            frequency = f"Runs every {job.interval} days"
        elif job.unit == "weeks" and job.start_day:
            frequency = (
                f"Runs every {job.start_day} at {
                    job.at_time.strftime('%H:%M:%S')}"
                if job.at_time
                else f"Runs every {job.start_day}"
            )
        else:
            frequency = f"Runs every {job.interval} {job.unit}"

        reminder = (
            f"- Reminder: Message: {job.job_func.func.message}, Once: {once}, "  # type: ignore
            f"{f'Last Run: {last_run}, ' if last_run else ''}"
            f"Schedule: {frequency}, ID: {job.job_func.func.id}, "  # type: ignore
            f"{'Skip Next: Yes, ' if job.job_func.func.skip_next else ''}"  # type: ignore
            f"{'Re-Remind: Yes' if job.job_func.func.re_remind else ''}"  # type: ignore
            "\n"
        )
        reminders += reminder
    if reminders == "\nReminders:\n":
        return "\n- No reminders set\n"
    return reminders

def CreateReminder(
    message: str,
    interval_type: Literal["minute", "hour", "day", "week"],
    interval_int: int,
    interval_list: list[Literal["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]],
    specific_time: str,
    once: bool,
) -> int:
    """
    Use this function to create reminders.

    Parameters:
    - message (str): The reminder message.
    - interval_type (Literal): Defines the interval type ('minute', 'hour', 'day', 'week').
    - interval_int (int):
      - Used for 'minute' (e.g., `5` for every 5 minutes), 'hour' (e.g., `2` for every 2 hours), and 'day' (e.g., `3` for every 3 days).
      - Pass `0` if using `interval_list` for 'week'.
    - interval_list (List[str]):
      - Used for 'week' type (e.g., ['monday', 'wednesday']).
      - Pass an empty list if using `interval_int` for 'minute', 'hour', or 'day'.
    - specific_time (str): The time in "HH:MM" format for 'day' or 'week' types (e.g., "08:30").
    - once (bool): If True, the reminder triggers only once.

    Returns:
    - int: The ID of the scheduled reminder.
    """
    reminder = Reminder(message, once)
    
    if interval_type == "minute" and interval_int > 0:
        job = schedule.every(interval_int).minutes.do(reminder).tag("once" if once else "")
    elif interval_type == "hour" and interval_int > 0:
        job = schedule.every(interval_int).hours.do(reminder).tag("once" if once else "")
    elif interval_type == "day":
        if specific_time:
            job = schedule.every().day.at(specific_time).do(reminder).tag("once" if once else "")
        elif interval_int > 0:
            job = schedule.every(interval_int).days.do(reminder).tag("once" if once else "")
        else:
            raise ValueError("Invalid interval for 'day'.")
    elif interval_type == "week" and interval_list:
        for day in interval_list:
            job = schedule.every().__getattribute__(day).at(specific_time).do(reminder).tag("once" if once else "")
    else:
        raise ValueError("Invalid interval type or parameters.")
    
    job.job_func.func.id = reminder.id  # type: ignore
    return job.job_func.func.id  # type: ignore

def CancelReminder(
    reminder_id: int, forever_or_next: Literal["forever", "next"]
) -> str:
    """
    Use this function to cancel a scheduled reminder by its ID.

    Parameters:
    - reminder_id (int): The ID of the reminder to cancel.
    - forever_or_next (Literal):
      - "forever": Permanently cancels the reminder.
      - "next": Skips the next scheduled occurrence, but keeps future ones.
    
    Returns:
    - str: The status message after cancelling the reminder.
    ```
    """
    for job in schedule.jobs:
        if job.job_func.func.id == reminder_id:  # type: ignore
            if forever_or_next == "forever":
                schedule.cancel_job(job)
                return f"Reminder with ID {reminder_id} has been cancelled forever."
            elif forever_or_next == "next":
                job.job_func.func.skip_next = True  # type: ignore
                return f"Next occurrence of reminder with ID {reminder_id} has been cancelled."
            else:
                raise ValueError("Invalid value for 'forever_or_next'.")
    raise Exception(f"Reminder with ID {reminder_id} not found, may have already been cancelled or expired.")
