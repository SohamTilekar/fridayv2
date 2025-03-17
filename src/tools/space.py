import os
import pathlib
from ..config import AI_DIR
import subprocess
import threading
import queue
import uuid
import signal
import shutil
from typing import Optional

space_path: pathlib.Path = AI_DIR / "friday_space"


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
    def run_command(command: str, timeout: Optional[int] = None) -> tuple[Optional[str], str, int]:
        """
        Runs a command in the sandbox and returns its output.

        Args:
            command (str): The command to run.
            timeout (Optional[int]): The timeout in seconds.

        Returns:
            tuple[Optional[str], str, int]: A tuple containing stdout, stderr, and the return code.
        """
        try:
            result = subprocess.run(
                command, shell=True, capture_output=True, text=True, cwd=space_path, timeout=timeout
            )
            return result.stdout, result.stderr, result.returncode
        except subprocess.TimeoutExpired:
            return None, "Command timed out", 1
        except Exception as e:
            return None, str(e), 1

    @staticmethod
    def create_file(relative_path: str, content: str = "") -> tuple[bool, Optional[str]]:
        """
        Creates a file in the sandbox with the given content.

        Args:
            relative_path (str): The relative path to the file.
            content (str): The content to write to the file.

        Returns:
            tuple[bool, Optional[str]]: A tuple containing a boolean indicating success and an optional error message.
        """
        full_path: pathlib.Path = space_path / relative_path
        try:
            with open(full_path, "w") as f:
                f.write(content)
            return True, None
        except Exception as e:
            return False, str(e)

    @staticmethod
    def create_folder(relative_path: str) -> tuple[bool, Optional[str]]:
        """
        Creates a folder in the sandbox.

        Args:
            relative_path (str): The relative path to the folder.

        Returns:
            tuple[bool, Optional[str]]: A tuple containing a boolean indicating success and an optional error message.
        """
        full_path: pathlib.Path = space_path / relative_path
        try:
            os.makedirs(full_path, exist_ok=True)
            return True, None
        except Exception as e:
            return False, str(e)

    @staticmethod
    def delete_file(relative_path: str) -> tuple[bool, Optional[str]]:
        """
        Deletes a file in the sandbox.

        Args:
            relative_path (str): The relative path to the file.

        Returns:
            tuple[bool, Optional[str]]: A tuple containing a boolean indicating success and an optional error message.
        """
        full_path: pathlib.Path = space_path / relative_path
        try:
            os.remove(str(full_path))  # os.remove needs string
            return True, None
        except FileNotFoundError:
            return False, "File not found"
        except Exception as e:
            return False, str(e)

    @staticmethod
    def delete_folder(relative_path: str) -> tuple[bool, Optional[str]]:
        """
        Deletes a folder in the sandbox.

        Args:
            relative_path (str): The relative path to the folder.

        Returns:
            tuple[bool, Optional[str]]: A tuple containing a boolean indicating success and an optional error message.
        """
        full_path: pathlib.Path = space_path / relative_path
        try:
            shutil.rmtree(full_path)
            return True, None
        except FileNotFoundError:
            return False, "Folder not found"
        except Exception as e:
            return False, str(e)

    @staticmethod
    def run_command_background(command: str) -> str:
        """
        Runs a command in the background and returns a process ID.

        Args:
            command (str): The command to run.

        Returns:
            str: The process ID.
        """
        process_id: str = str(uuid.uuid4())
        cmd_queue: queue.Queue[Optional[str]] = queue.Queue()
        env = CodeExecutionEnvironment()

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
    def send_stdin(process_id: str, input_str: str) -> tuple[bool, Optional[str]]:
        """
        Sends input to a background process.

        Args:
            process_id (str): The ID of the process.
            input_str (str): The input string to send.

        Returns:
            tuple[bool, Optional[str]]: A tuple containing a boolean indicating success and an optional error message.
        """
        env = CodeExecutionEnvironment()
        if process_id not in CodeExecutionEnvironment.processes:
            return False, "Process not found"

        process = CodeExecutionEnvironment.processes[process_id]
        try:
            if process.stdin:
                process.stdin.write(input_str + "\n")
                process.stdin.flush()
            return True, None
        except Exception as e:
            return False, str(e)

    @staticmethod
    def get_stdout(process_id: str) -> tuple[Optional[list[str]], Optional[str]]:
        """
        Gets any available stdout from a background process.

        Args:
            process_id (str): The ID of the process.

        Returns:
            tuple[Optional[list[str]], Optional[str]]: A tuple containing a list of stdout lines and an optional error message.
        """
        env = CodeExecutionEnvironment()
        if process_id not in CodeExecutionEnvironment.process_queues:
            return None, "Process not found"

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
        return output, None

    @staticmethod
    def is_process_running(process_id: str) -> bool:
        """
        Checks if a process is currently running.

        Args:
            process_id (str): The ID of the process.

        Returns:
            bool: True if the process is running, False otherwise.
        """
        env = CodeExecutionEnvironment()
        if process_id not in CodeExecutionEnvironment.processes:
            return False
        return CodeExecutionEnvironment.processes[process_id].poll() is None

    @staticmethod
    def kill_process(process_id: str) -> tuple[bool, Optional[str]]:
        """
        Kills a background process.

        Args:
            process_id (str): The ID of the process.

        Returns:
            tuple[bool, Optional[str]]: A tuple containing a boolean indicating success and an optional error message.
        """
        env = CodeExecutionEnvironment()
        if process_id not in CodeExecutionEnvironment.processes:
            return False, "Process not found"

        process = CodeExecutionEnvironment.processes[process_id]
        try:
            process.terminate()
            process.wait()
            return True, None
        except Exception as e:
            return False, str(e)

    @staticmethod
    def send_control_c(process_id: str) -> tuple[bool, Optional[str]]:
        """
        Sends a Ctrl+C signal to a background process.

        Args:
            process_id (str): The ID of the process.

        Returns:
            tuple[bool, Optional[str]]: A tuple containing a boolean indicating success and an optional error message.
        """
        env = CodeExecutionEnvironment()
        if process_id not in CodeExecutionEnvironment.processes:
            return False, "Process not found"

        process = CodeExecutionEnvironment.processes[process_id]
        try:
            if os.name == "nt":
                os.kill(process.pid, signal.CTRL_BREAK_EVENT)
            else:
                process.send_signal(signal.SIGINT)
            return True, None
        except Exception as e:
            return False, str(e)

    @staticmethod
    def read_file(relative_path: str) -> tuple[Optional[str], Optional[str]]:
        """
        Reads the content of a file in the sandbox.

        Args:
            relative_path (str): The relative path to the file.

        Returns:
            tuple[Optional[str], Optional[str]]: A tuple containing the file content and an optional error message.
        """
        full_path: pathlib.Path = space_path / relative_path
        try:
            with open(full_path, "r") as f:
                content: str = f.read()
            return content, None
        except FileNotFoundError:
            return None, "File not found"
        except Exception as e:
            return None, str(e)

    @staticmethod
    def write_file(relative_path: str, content: str) -> tuple[bool, Optional[str]]:
        """
        Writes content to a file in the sandbox.

        Args:
            relative_path (str): The relative path to the file.
            content (str): The content to write to the file.

        Returns:
            tuple[bool, Optional[str]]: A tuple containing a boolean indicating success and an optional error message.
        """
        full_path: pathlib.Path = space_path / relative_path
        try:
            with open(full_path, "w") as f:
                f.write(content)
            return True, None
        except Exception as e:
            return False, str(e)
