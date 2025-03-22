# lschedule.py
import json
from pathlib import Path
import uuid
from typing import Optional

class Task:
    def __init__(self, id: Optional[str] = None, title: str = "", start: Optional[str] = None, end: Optional[str] = None, allDay: bool = True, backgroundColor: str = "#000000", borderColor: str = "#000000", completed: bool = False):
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
    def load_from_json(filepath: str) -> "Schedule":
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
