import mimetypes
import os
import pathlib
from config import AI_DIR
import subprocess
import threading
import queue
import uuid
import signal
import shutil
from typing import Optional
from global_shares import global_shares

space_path: pathlib.Path = AI_DIR / "friday_space"


class PermisionError(Exception):
    """
    Raise When User declines permision for perticular task
    """
    ...

class CodeExecutionEnvironment:
    """
    A singleton class that provides a environment for executing code.
    """

    _instance: Optional["CodeExecutionEnvironment"] = None
    processes: dict[str, subprocess.Popen[str]] = {}
    process_queues: dict[str, queue.Queue[Optional[str]]] = {}

    def __new__(cls) -> "CodeExecutionEnvironment":
        """
        Creates a singleton instance of the CodeExecutionEnvironment.
        """
        if not cls._instance:
            cls._instance = super().__new__(cls)
        return cls._instance

    @staticmethod
    def RunCommand(command: str, timeout: Optional[int] = None) -> tuple[str, str, int]:
        """
        Runs a command in the sandbox and returns its output.

        Args:
            command (str): The command to run.
            timeout (Optional[int]): The timeout in seconds, None for no time out.

        Returns:
            tuple[str, str, int]: A tuple containing stdout, stderr, and the return code.
        """
        if not global_shares["take_permision"](f"Permission for running following command: `{command}`"):
            raise PermisionError("User Declined Permission to run command.")
        result = subprocess.run(
            command, shell=True, capture_output=True, text=True, cwd=space_path, timeout=timeout
        )
        return result.stdout, result.stderr, result.returncode

    @staticmethod
    def CreateFile(relative_path: str, content: Optional[str] = None):
        """
        Creates a file in the sandbox with the given content.

        Args:
            relative_path (str): The relative path to the file.
            content (Optional[str]): The content to write to the file.
        """
        if not global_shares["take_permision"](f"Permission for Creating file: `{relative_path}`"):
            raise PermisionError("User Declined Permission to create file.")
        full_path: pathlib.Path = space_path / relative_path
        with open(full_path, "w") as f:
            f.write(content or "")

    @staticmethod
    def CreateFolder(relative_path: str):
        """
        Creates a folder in the sandbox.

        Args:
            relative_path (str): The relative path to the folder.
        """
        if not global_shares["take_permision"](f"Permission for Creating folder: `{relative_path}`"):
            raise PermisionError("User Declined Permission to create folder.")
        full_path: pathlib.Path = space_path / relative_path
        os.makedirs(full_path, exist_ok=True)

    @staticmethod
    def DeleteFile(relative_path: str):
        """
        Deletes a file in the sandbox.

        Args:
            relative_path (str): The relative path to the file.
        """
        if not global_shares["take_permision"](f"Permission for Deleting file: `{relative_path}`"):
            raise PermisionError("User Declined Permission to delete file.")
        full_path: pathlib.Path = space_path / relative_path
        os.remove(str(full_path))

    @staticmethod
    def DeleteFolder(relative_path: str):
        """
        Deletes a folder in the sandbox.

        Args:
            relative_path (str): The relative path to the folder.
        """
        if not global_shares["take_permision"](f"Permission for Deleting folder: `{relative_path}`"):
            raise PermisionError("User Declined Permission to delete folder")
        full_path: pathlib.Path = space_path / relative_path
        shutil.rmtree(full_path)

    @staticmethod
    def RunCommandBackground(command: str) -> str:
        """
        Runs a command in the background and returns a process ID.

        Args:
            command (str): The command to run.

        Returns:
            str: The process ID.
        """
        if not global_shares["take_permision"](f"Permission for running background command: `{command}`"):
            raise PermisionError("User Declined Permission to run background command")
        process_id: str = str(uuid.uuid4())
        cmd_queue: queue.Queue[Optional[str]] = queue.Queue()

        def run():
            try:
                process = subprocess.Popen(
                    command,
                    shell=True,
                    cwd=space_path,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    start_new_session=True,
                )
                CodeExecutionEnvironment.processes[process_id] = process
                CodeExecutionEnvironment.process_queues[process_id] = cmd_queue

                if process.stdout:
                    while True:
                        line = process.stdout.readline()
                        if not line:
                            break
                        cmd_queue.put(line.strip())

                if process.stderr:
                    for line in process.stderr:
                        cmd_queue.put(f"stderr: {line.strip()}")

                process.wait()
                cmd_queue.put(None)

                if process.stdout:
                    process.stdout.close()
                if process.stderr:
                    process.stderr.close()

                del CodeExecutionEnvironment.processes[process_id]
                del CodeExecutionEnvironment.process_queues[process_id]

            except Exception as e:
                cmd_queue.put(f"Error: {str(e)}")
                cmd_queue.put(None)

        thread = threading.Thread(target=run)
        thread.daemon = True
        thread.start()
        return process_id

    @staticmethod
    def SendSTDIn(process_id: str, input_str: str):
        """
        Sends input to a background process.

        Args:
            process_id (str): The ID of the process.
            input_str (str): The input string to send.
        """
        if not global_shares["take_permision"](f"Permission for sending input to process: `{process_id}`"):
            raise PermisionError("User Declined Permission to send input")
        if process_id not in CodeExecutionEnvironment.processes:
            raise ValueError("Process not found")

        process = CodeExecutionEnvironment.processes[process_id]
        if process.stdin:
            process.stdin.write(input_str + "\n")
            process.stdin.flush()

    @staticmethod
    def GetSTDOut(process_id: str):
        """
        Gets any available stdout from a background process.

        Args:
            process_id (str): The ID of the process.
        
        Return:
            list[str]: STDOut of the peocess
        """
        if process_id not in CodeExecutionEnvironment.process_queues:
            raise ValueError("Process not found")

        cmd_queue = CodeExecutionEnvironment.process_queues[process_id]
        output: list[str] = []
        try:
            while True:
                line = cmd_queue.get_nowait()
                if line is None:
                    break
                output.append(line)
        except queue.Empty:
            pass
        return output

    @staticmethod
    def IsProcessRunning(process_id: str) -> bool:
        """
        Checks if a process is currently running.

        Args:
            process_id (str): The ID of the process.

        Returns:
            bool: True if the process is running, False otherwise.
        """
        if process_id not in CodeExecutionEnvironment.processes:
            return False
        return CodeExecutionEnvironment.processes[process_id].poll() is None

    @staticmethod
    def KillProcess(process_id: str):
        """
        Kills a background process.

        Args:
            process_id (str): The ID of the process.
        """
        if not global_shares["take_permision"](f"Permission for killing process: `{process_id}`"):
            raise PermisionError("User Declined Permission to kill process")
        if process_id not in CodeExecutionEnvironment.processes:
            raise ValueError("Process not found")

        process = CodeExecutionEnvironment.processes[process_id]
        process.terminate()
        process.wait()
    
    @staticmethod
    def SendControlC(process_id: str):
        """
        Sends a Ctrl+C signal to a background process.

        Args:
            process_id (str): The ID of the process.
        """
        if not global_shares["take_permision"](f"Permission for sending Ctrl+C to process: `{process_id}`"):
            raise PermisionError("User Declined Permission to send Ctrl+C")
        if process_id not in CodeExecutionEnvironment.processes:
            raise ValueError("Process not found")

        process = CodeExecutionEnvironment.processes[process_id]
        if os.name == "nt":
            os.kill(process.pid, signal.CTRL_BREAK_EVENT)
        else:
            process.send_signal(signal.SIGINT)

    @staticmethod
    def ReadFile(relative_path: str) -> Optional[str]:
        """
        Reads the content of a file in the sandbox.

        Args:
            relative_path (str): The relative path to the file.

        Returns:
            Optional[str]: File content.
        """
        if not global_shares["take_permision"](f"Permission for reading file: `{relative_path}`"):
            raise PermisionError("User Declined Permission to read file")
        full_path: pathlib.Path = space_path / relative_path
        with open(full_path, "r") as f:
            content: str = f.read()
        return content

    @staticmethod
    def WriteFile(relative_path: str, content: str):
        """
        Writes content to a file in the sandbox.

        Args:
            relative_path (str): The relative path to the file.
            content (str): The content to write to the file.
        """
        if not global_shares["take_permision"](f"Permission for writing file: `{relative_path}`"):
            raise PermisionError("User Declined Permission to write file")
        full_path: pathlib.Path = space_path / relative_path
        with open(full_path, "w") as f:
            f.write(content)

    @staticmethod
    def LinkAttachment(relative_paths: list[str]) -> str:
        """
        Links the given attachments to the message for display to the user.

        **Supported file types:**
        - **Images**: png, jpeg, webp, heic, heif
        - **Videos**: mp4, mpeg, mov, avi, flv, mpg, webm, wmv, 3gpp
        - **Text files**: txt, json, py, cpp, c, etc. (Any text-based format)
        - **PDF**: pdf

        **Parameters:**
        - `relative_paths` (list[str]): A list of relative file paths to be linked.

        **Returns:**
        - `str`: A message confirming the successful attachment of the files.

        **Raises:**
        - `ValueError`: If a file does not exist.
        - `ValueError`: If a file type is unsupported or its MIME type cannot be determined.
        """
        supported_image_types = ["image/png", "image/jpeg", "image/webp", "image/heic", "image/heif"]
        supported_video_types = ["video/mp4", "video/mpeg", "video/quicktime", "video/x-msvideo", "video/x-flv", "video/mpeg", "video/webm", "video/x-ms-wmv", "video/3gpp"]

        for relative_path in relative_paths:
            file_path = space_path / relative_path
            if not os.path.exists(file_path):
                raise ValueError(f"File `{relative_path}` not found")

            mime_type, _ = mimetypes.guess_type(file_path)

            if mime_type is None:
                raise ValueError(f"Could not determine MIME type for file `{relative_path}`")

            if mime_type.startswith("text/"):
                continue
            elif mime_type in supported_image_types:
                continue
            elif mime_type in supported_video_types:
                continue
            elif mime_type == "application/pdf":
                continue
            else:
                raise ValueError(f"File type `{mime_type}` for file `{relative_path}` is not supported")

        return f"{"File is" if len(relative_paths) is 1 else "Files are"} attached below."

    @staticmethod
    def dir_tree() -> str:
        """
        Return a directory ANSI tree as a sting in sandbox.
        """
        tree_str = "Computer Sandbox Directory Tree:\n"
        root_path = pathlib.Path(space_path)

        if not root_path.exists():
            return f"Error: Path '{space_path}' does not exist."
        if not root_path.is_dir():
            return f"Error: Path '{space_path}' is not a directory."

        tree_str += f"{root_path.name}\n"

        def generate_tree(directory: pathlib.Path, prefix: str = "", is_last: bool = False) -> str:
            nonlocal tree_str

            items = sorted(list(directory.iterdir()), key=lambda x: x.name)

            if not items:
                return ""

            for index, item in enumerate(items):
                is_item_last = (index == len(items) - 1)
                if item.is_dir():
                    if is_item_last:
                        tree_str += f"{prefix}└── {item.name}\n"
                        generate_tree(item, prefix + "    ", is_last=True)
                    else:
                        tree_str += f"{prefix}├── {item.name}\n"
                        generate_tree(item, prefix + "│   ", is_last=False)
                elif item.is_file():
                    if is_item_last:
                        tree_str += f"{prefix}└── {item.name}\n"
                    else:
                        tree_str += f"{prefix}├── {item.name}\n"
            return ""  # Return is not strictly needed, but good practice

        generate_tree(root_path)
        return tree_str
