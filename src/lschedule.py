# lschedule.py
import json
from pathlib import Path
import uuid
from typing import Optional
from datetime import datetime
from global_shares import global_shares

class Task:
    def __init__(self, id: Optional[str] = None, title: str = "", start: Optional[str] = None, end: Optional[str] = None, allDay: bool = False, backgroundColor: str = "#000000", borderColor: str = "#000000", completed: bool = False):
        self.id = id or str(uuid.uuid4())
        self.title = title
        self.start = start
        self.end = end
        self.allDay = allDay
        self.backgroundColor = backgroundColor
        self.borderColor = borderColor
        self.completed = completed

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "start": self.start,
            "end": self.end,
            "allDay": self.allDay,
            "backgroundColor": self.backgroundColor,
            "borderColor": self.borderColor,
            "completed": self.completed,
        }

    @staticmethod
    def from_dict(data: dict) -> "Task":
        return Task(
            id=data.get("id"),
            title=data.get("title", ""),
            start=data.get("start"),
            end=data.get("end"),
            allDay=data.get("allDay", True),
            backgroundColor=data.get("backgroundColor", "#000000"),
            borderColor=data.get("borderColor", "#000000"),
            completed=data.get("completed", False),
        )


class Schedule:
    def __init__(self, tasks: Optional[list[Task]] = None):
        self.tasks: list[Task] = tasks or []

    def add_task(self, task: Task):
        self.tasks.append(task)

    def update_task(self, task: Task):
        for i, t in enumerate(self.tasks):
            if t.id == task.id:
                self.tasks[i] = task
                return
        raise ValueError(f"Task with id {task.id} not found")
    
    def get_task(self, task_id: str) -> Task:
        for task in self.tasks:
            if task.id == task_id:
                return task
        raise ValueError(f"Task with id {task_id} not found")

    def delete_task(self, task_id: str):
        self.tasks = [t for t in self.tasks if t.id != task_id]

    def to_dict(self) -> dict:
        return {"tasks": [task.to_dict() for task in self.tasks]}

    @staticmethod
    def from_dict(data: dict) -> "Schedule":
        return Schedule(tasks=[Task.from_dict(task_data) for task_data in data.get("tasks", [])])

    def save_to_json(self, filepath: Path):
        with open(filepath, "w") as f:
            json.dump(self.to_dict(), f, indent=4)

    @staticmethod
    def load_from_json(filepath: Path) -> "Schedule":
        try:
            with open(filepath, "r") as f:
                data = json.load(f)
                return Schedule.from_dict(data)
        except FileNotFoundError:
            return Schedule()  # Return an empty schedule if file not found
        except json.JSONDecodeError:
            print("Error decoding schedule JSON.  Returning an empty schedule.")
            return Schedule()


schedule = Schedule()  # Create a global instance

def get_todo_list_string() -> str:
    """
    Returns the TODO list in a string format, including start/end times, and completion status.
    """
    todo_list = []
    for task in schedule.tasks:
        status = "[Completed]" if task.completed else "[Incomplete]"
        time_info = ""
        if task.start:
            time_info += f", Start: {task.start}"
            if task.end:
                time_info += f", End: {task.end}"
        else:
            time_info = "[Not Planned]"

        todo_list.append(f"- {status} Title: `{task.title}` {time_info}, ID: `{task.id}`")

    return f"Todays Date: {datetime.now().strftime('%Y-%m-%d %a')}\nTasks:\n" + ("\n".join(todo_list) or "No Tasks in todo list")

import random

def get_random_color() -> str:
    """
    Generates a random hex color string that satisfies certain validity criteria.
    """
    color = '#000000'
    while not is_valid_color(color):
        color = '#' + hex(random.randint(0, 16777215))[2:].zfill(6)
    return color

def is_valid_color(color: str) -> bool:
    """
    Checks if a hex color string is valid based on brightness and saturation criteria.
    """
    # Convert hex color to RGB
    r = int(color[1:3], 16)
    g = int(color[3:5], 16)
    b = int(color[5:7], 16)

    # Define color range restrictions
    min_brightness = 50  # Adjust as needed
    max_brightness = 200  # Adjust as needed
    brightness = (r + g + b) / 3

    # Example restrictions:
    if brightness < min_brightness or brightness > max_brightness:
        return False  # Reject colors that are too dark or too light

    # Example restrictions: Avoid very saturated colors
    max_saturation = 150  # Adjust as needed
    max_diff = max(r, g, b) - min(r, g, b)
    if max_diff > max_saturation:
        return False  # Reject very saturated colors

    return True  # Color is valid

def CreateTask(title: str, start_date: Optional[str], start_time: Optional[str], end_date: Optional[str], end_time: Optional[str], allDay: bool, completed: bool) -> str:
    """
    Creates a new task and adds it to the schedule.

    Args:
        title (str): The title of the task.
        start_date str | None): The start date of the task in YYYY-MM-DD format (e.g., "2024-03-15").
                                     Must be string if start_time is string.
        start_time (str | None): The start time of the task in HH:MM format (24-hour) (e.g., "14:30").
        end_date (str | None): The end date of the task in YYYY-MM-DD format.
                                   Must be string if end_time is string.
        end_time (str | None): The end time of the task in HH:MM format (24-hour).
        allDay (bool): True if the task is an all-day event, False otherwise.
        completed (bool): True if the task is completed, False otherwise.

    Returns:
        str: String the error or success message

    Example:
        To create a task "Meeting with John" on March 15, 2024, from 2:30 PM to 3:30 PM:
        ```python
        create_task(
            title="Meeting with John",
            start_date="2024-03-15",
            start_time="14:30",
            end_date="2024-03-15",
            end_time="15:30",
            allDay=False,
            completed=False
        )
        ```

        To create an all-day task "Grocery Shopping" on March 16, 2024:
        ```python
        create_task(
            title="Grocery Shopping",
            start_date="2024-03-16",
            start_time=None,
            end_date=None,
            end_time=None,
            allDay=True,
            completed=False
        )
        ```
    """
    if (start_time and not start_date) or (start_date and not start_time):
        return "Both start_date and start_time must be provided together."

    if (end_time and not end_date) or (end_date and not end_time):
        return "Both end_date and end_time must be provided together."

    color = get_random_color()
    schedule.add_task(
        Task(
            title=title,
            start=f"{start_date}T{start_time}" if start_time else start_date,
            end=f"{end_date}T{end_time}" if end_time else end_date,
            allDay=allDay,
            backgroundColor=color,
            borderColor=color,
            completed=completed
        )
    )
    if global_shares["socketio"]:
        global_shares["socketio"].emit("schedule_update", schedule.to_dict())
    return "Task Successfully created"

def UpdateTask(task_id: str, title: Optional[str], start_date: Optional[str], start_time: Optional[str], end_date: Optional[str], end_time: Optional[str], allDay: Optional[bool], completed: Optional[bool]) -> str:
    """
    Updates an existing task in the schedule.

    Args:
        task_id (str): The ID of the task to update.
        title (str | None): The new title of the task. If None, the title will not be updated.
        start_date (str | None): The new start date of the task in YYYY-MM-DD format.
        start_time (str | None): The new start time of the task in HH:MM format (24-hour).
        end_date (str | None): The new end date of the task in YYYY-MM-DD format.
        end_time (str | None): The new end time of the task in HH:MM format (24-hour).
        allDay (bool): The new allDay status of the task.
        completed (bool): The new completion status of the task.

    Returns:
        str: A success or error message.

    Raises:
        ValueError: If the task with the given ID is not found.

    Example:
        To update the title of a task with ID "12345" to "Updated Meeting with John":
        ```python
        update_task(task_id="12345", title="Updated Meeting with John")
        ```

        To mark a task with ID "12345" as completed:
        ```python
        update_task(task_id="12345", completed=True)
        ```

        To update the start and end times of a task with ID "12345":
        ```python
        update_task(
            task_id="12345",
            start_date="2024-03-16",
            start_time="10:00",
            end_date="2024-03-16",
            end_time="11:00"
        )
        ```
    """
    task = schedule.get_task(task_id)

    if title is not None:
        task.title = title
    if start_date is not None:
        task.start = f"{start_date}T{start_time}" if start_time else start_date
    if end_date is not None:
        task.end = f"{end_date}T{end_time}" if end_time else end_date
    if allDay is not None:
        task.allDay = allDay
    if completed is not None:
        task.completed = completed
    schedule.update_task(task)
    if global_shares["socketio"]:
        global_shares["socketio"].emit("schedule_update", schedule.to_dict())
    return f"Task with ID '{task_id}' successfully updated."
