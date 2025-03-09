import os
import pathlib
import shutil
import sys
import tempfile
import time
from ..config import AI_DIR
import subprocess
import threading
import queue
import uuid  # For generating unique IDs
import signal # For sending signals
import functools
from typing import Callable

space_path: pathlib.Path = AI_DIR/"friday_space"
external_write_permissions = set()  # Store paths that have been granted write permission
monitoring_interval = 1  # seconds

# Create a temporary directory to hold our custom open module
temp_dir = tempfile.mkdtemp()
custom_open_module_path = os.path.join(temp_dir, "custom_open.py")

# Write the custom open module
with open(custom_open_module_path, "w") as f:
    f.write("""
import builtins
import os

external_write_permissions = set()

def take_permission(filepath):
    print(f"Subprocess WARNING: Attempt to write to external file: {filepath}!")
    response = input("Allow write (y/n)? ")
    if response.lower() == 'y':
        external_write_permissions.add(os.path.abspath(filepath))
        return True
    return False

def check_write_permission(filepath):
    return os.path.abspath(filepath) in external_write_permissions

original_open = builtins.open

def open(filepath, mode='r', buffering=-1, encoding=None, errors=None, newline=None, closefd=True, opener=None):
    abs_filepath = os.path.abspath(filepath)
    if not abs_filepath.startswith("/"):
        return original_open(filepath, mode, buffering, encoding, errors, newline, closefd, opener)

    if 'w' in mode or 'a' in mode or '+' in mode:
        if not check_write_permission(filepath):
            if not take_permission(filepath):
                raise PermissionError(f"Write denied: {filepath}")
    return original_open(filepath, mode, buffering, encoding, errors, newline, closefd, opener)

builtins.open = open
""")

# Add the temporary directory to sys.path
sys.path.insert(0, temp_dir)

def get_directory_tree(path, indent=""):
    """
    Generates a string representation of the directory tree for a given relative path from the sandbox root.
    e.g: get_directory_tree("my_project/xyz/")

    Args:
        path (str): The relative path to the directory within space_path.

    Returns:
        str: A string representing the directory tree.
    """
    tree = ""
    full_path = space_path / path  # Combine space_path with the relative path

    try:
        items = os.listdir(full_path)
    except OSError as e:
        return f"{indent}Error accessing {path}: {e}\n"

    for item in items:
        item_path = os.path.join(full_path, item)
        tree += f"{indent}├── {item}\n"
        if os.path.isdir(item_path):
            tree += get_directory_tree(os.path.relpath(item_path, space_path), indent + "│   ")  # Recursive call with relative path
    return tree

def check_write_permission(filepath):
    """Checks if write permission has been granted for the given filepath."""
    return os.path.abspath(filepath) in external_write_permissions

take_permission: Callable[[str], bool] = lambda filepath: (_ for _ in ()).throw(PermissionError(f"Write access is disabled: {filepath}"))

def restricted_open(func):
    """Decorator to restrict file access."""
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        filepath = args[0] if args else None  # Assume filepath is the first argument
        if filepath:
            abs_filepath = os.path.abspath(filepath)
            if not abs_filepath.startswith(str(space_path)):  # Check if outside space_path
                mode = args[1] if len(args) > 1 else kwargs.get('mode', 'r')
                if 'w' in mode or 'a' in mode or '+' in mode:  # Check if it's a write operation
                    if not check_write_permission(filepath):
                        if not take_permission(filepath):
                            raise PermissionError(f"Write permission denied for {filepath}")
        return func(*args, **kwargs)
    return wrapper

# Apply the restriction to the built-in open function
open = restricted_open(open)

class SandBox:
    _instance = None

    def __new__(cls):
        if not cls._instance:
            cls._instance = super(SandBox, cls).__new__(cls)
        return cls._instance

    def __init__(self):
        if not hasattr(self, 'processes'):  # Ensure initialization only happens once
            self.processes = {}  # Map of process_id: subprocess.Popen object
            self.process_queues = {} # Map of process_id: queue object

    @staticmethod
    def run_command(command, timeout=None):
        """Runs a command in the sandbox and returns its output."""
        sandbox = SandBox()
        try:
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                cwd=space_path,
                timeout=timeout
            )
            return result.stdout, result.stderr, result.returncode
        except subprocess.TimeoutExpired:
            return None, "Command timed out", 1

    @staticmethod
    def create_file(relative_path, content=""):
        """Creates a file in the sandbox with the given content."""
        sandbox = SandBox()
        full_path = space_path / relative_path
        try:
            with open(full_path, "w") as f:
                f.write(content)
            return True, None
        except Exception as e:
            return False, str(e)

    @staticmethod
    def create_folder(relative_path):
        """Creates a folder in the sandbox."""
        sandbox = SandBox()
        full_path = space_path / relative_path
        try:
            os.makedirs(full_path, exist_ok=True)
            return True, None
        except Exception as e:
            return False, str(e)

    @staticmethod
    def delete_file(relative_path):
        """Deletes a file in the sandbox."""
        sandbox = SandBox()
        full_path = space_path / relative_path
        try:
            os.remove(full_path)
            return True, None
        except FileNotFoundError:
            return False, "File not found"
        except Exception as e:
            return False, str(e)

    @staticmethod
    def delete_folder(relative_path):
        """Deletes a folder in the sandbox (recursively)."""
        sandbox = SandBox()
        full_path = space_path / relative_path
        try:
            import shutil
            shutil.rmtree(full_path)
            return True, None
        except FileNotFoundError:
            return False, "Folder not found"
        except Exception as e:
            return False, str(e)

    @staticmethod
    def run_command_background(command):
        """Runs a command in the background and returns a process ID."""
        sandbox = SandBox()
        process_id = str(uuid.uuid4())  # Generate a unique ID
        cmd_queue = queue.Queue() # Use a different name to avoid shadowing

        def run():
            try:
                # Set LD_PRELOAD environment variable
                env = os.environ.copy()
                env["PYTHONPATH"] = temp_dir  # Use our custom open

                process = subprocess.Popen(
                    command,
                    shell=True,
                    cwd=space_path,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    start_new_session=True # Very important for sending Ctrl+C
                )
                sandbox.processes[process_id] = process  # Store the process
                sandbox.process_queues[process_id] = cmd_queue

                # Read from stdout if it exists
                if process.stdout:
                    while True:
                        line = process.stdout.readline()
                        if not line:
                            break
                        cmd_queue.put(line.strip())  # Send stdout to the queue

                # Read from stderr if it exists
                if process.stderr:
                    for line in process.stderr:
                        cmd_queue.put(f"stderr: {line.strip()}")

                process.wait()
                cmd_queue.put(None)  # Signal completion

                # Ensure streams are closed before deleting
                if process.stdout:
                    process.stdout.close()
                if process.stderr:
                    process.stderr.close()

                del sandbox.processes[process_id]
                del sandbox.process_queues[process_id]

            except Exception as e:
                cmd_queue.put(f"Error: {str(e)}")
                cmd_queue.put(None)

        thread = threading.Thread(target=run)
        thread.daemon = True  # Allow the main program to exit even if the thread is running
        thread.start()
        return process_id

    @staticmethod
    def send_stdin(process_id, input_str):
        """Sends input to a background process."""
        sandbox = SandBox()
        if process_id not in sandbox.processes:
            return False, "Process not found"

        process = sandbox.processes[process_id]
        try:
            process.stdin.write(input_str + "\n")  # Add newline for typical command-line behavior
            process.stdin.flush()  # Ensure the input is sent immediately
            return True, None
        except Exception as e:
            return False, str(e)

    @staticmethod
    def get_stdout(process_id):
        """Gets any available stdout from a background process."""
        sandbox = SandBox()
        if process_id not in sandbox.process_queues:
            return None, "Process not found"

        cmd_queue = sandbox.process_queues[process_id]
        output = []
        try:
            while True:
                line = cmd_queue.get_nowait()  # Non-blocking get
                if line is None:
                    break  # Process completed
                output.append(line)
        except queue.Empty:
            pass  # No output available at this time
        return output, None

    @staticmethod
    def is_process_running(process_id):
        """Checks if a process is currently running."""
        sandbox = SandBox()
        if process_id not in sandbox.processes:
            return False
        return sandbox.processes[process_id].poll() is None # None means still running

    @staticmethod
    def kill_process(process_id):
        """Kills a background process."""
        sandbox = SandBox()
        if process_id not in sandbox.processes:
            return False, "Process not found"

        process = sandbox.processes[process_id]
        try:
            process.terminate()  # Or process.kill() for a more forceful termination
            process.wait()
            return True, None
        except Exception as e:
            return False, str(e)

    @staticmethod
    def send_control_c(process_id):
        """Sends a Ctrl+C signal to a background process."""
        sandbox = SandBox()  # Get the singleton instance
        if process_id not in sandbox.processes:
            return False, "Process not found"

        process = sandbox.processes[process_id]
        try:
            if os.name == 'nt':
                # Ctrl+C on Windows requires sending the signal to the process group
                os.kill(process.pid, signal.CTRL_BREAK_EVENT)
            else:
                process.send_signal(signal.SIGINT) # Send SIGINT (Ctrl+C)
            return True, None
        except Exception as e:
            return False, str(e)

    @staticmethod
    def read_file(relative_path):
        """Reads the content of a file in the sandbox."""
        sandbox = SandBox()
        full_path = space_path / relative_path
        try:
            with open(full_path, "r") as f:
                content = f.read()
            return content, None
        except FileNotFoundError:
            return None, "File not found"
        except Exception as e:
            return None, str(e)

    @staticmethod
    def write_file(relative_path, content):
        """Writes content to a file in the sandbox."""
        sandbox = SandBox()
        full_path = space_path / relative_path
        try:
            with open(full_path, "w") as f:
                f.write(content)
            return True, None
        except Exception as e:
            return False, str(e)
