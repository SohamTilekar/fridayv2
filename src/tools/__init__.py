import enum
from google.genai import types
from typing import Literal
import config

from .reminder import CreateReminder, save_jobs, run_reminders, get_reminders, CancelReminder
from .webfetch import FetchWebsite
from .space import CodeExecutionEnvironment

run_command = CodeExecutionEnvironment.run_command
run_command_background = CodeExecutionEnvironment.run_command_background
send_stdin = CodeExecutionEnvironment.send_stdin
get_stdout = CodeExecutionEnvironment.get_stdout
create_file = CodeExecutionEnvironment.create_file
create_folder = CodeExecutionEnvironment.create_folder
delete_file = CodeExecutionEnvironment.delete_file
delete_folder = CodeExecutionEnvironment.delete_folder
is_process_running = CodeExecutionEnvironment.is_process_running
kill_process = CodeExecutionEnvironment.kill_process
read_file = CodeExecutionEnvironment.read_file
write_file = CodeExecutionEnvironment.write_file
send_control_c = CodeExecutionEnvironment.send_control_c

FetchTool = types.Tool(function_declarations=[types.FunctionDeclaration.from_callable_with_api_option(callable=FetchWebsite)])
ReminderTool = types.Tool(function_declarations=[
    types.FunctionDeclaration.from_callable_with_api_option(callable=CreateReminder),
    types.FunctionDeclaration.from_callable_with_api_option(callable=CancelReminder)
])
SearchGrounding = types.Tool(google_search=types.GoogleSearch())
ComputerTool = types.Tool(
    function_declarations=[
        types.FunctionDeclaration.from_callable_with_api_option(callable=CodeExecutionEnvironment.run_command),
        types.FunctionDeclaration.from_callable_with_api_option(callable=CodeExecutionEnvironment.run_command_background),
        types.FunctionDeclaration.from_callable_with_api_option(callable=CodeExecutionEnvironment.send_stdin),
        types.FunctionDeclaration.from_callable_with_api_option(callable=CodeExecutionEnvironment.get_stdout),
        types.FunctionDeclaration.from_callable_with_api_option(callable=CodeExecutionEnvironment.create_file),
        types.FunctionDeclaration.from_callable_with_api_option(callable=CodeExecutionEnvironment.create_folder),
        types.FunctionDeclaration.from_callable_with_api_option(callable=CodeExecutionEnvironment.delete_file),
        types.FunctionDeclaration.from_callable_with_api_option(callable=CodeExecutionEnvironment.delete_folder),
        types.FunctionDeclaration.from_callable_with_api_option(callable=CodeExecutionEnvironment.is_process_running),
        types.FunctionDeclaration.from_callable_with_api_option(callable=CodeExecutionEnvironment.kill_process),
        types.FunctionDeclaration.from_callable_with_api_option(callable=CodeExecutionEnvironment.read_file),
        types.FunctionDeclaration.from_callable_with_api_option(callable=CodeExecutionEnvironment.write_file),
        types.FunctionDeclaration.from_callable_with_api_option(callable=CodeExecutionEnvironment.send_control_c),
    ]
)

type ToolLiteral = Literal["FetchWebsite", "Reminder", "SearchGrounding", "ComputerTool"]

class Tools(enum.Enum):
    FetchWebsite = FetchTool
    Reminder = ReminderTool
    SearchGrounding = SearchGrounding
    ComputerTool = ComputerTool
    @staticmethod
    def tool_names() -> list[Literal["FetchWebsite", "Reminder", "SearchGrounding", "ComputerTool"]]:
        return ["FetchWebsite", "Reminder", "SearchGrounding", "ComputerTool"]

def ModelAndToolSelector(
        model: Literal["Large20","Medium20","MediumThinking20","Small20","Large15","Medium15","Small15"],
        tools: list[Literal["FetchWebsite", "Reminder", "SearchGrounding", "ComputerTool"]]
    ) -> tuple[str, bool, list[types.Tool]]:
    f"""\
Use this tool to choose the best AI model with tools to respond to the user's request, considering the model capabilities, rate limits, latency, benchmark scores, and tool requirements.

If No tools want to provided then pass tools as empty list/array

**AI Model Benchmarks:**

Use these benchmarks to guide your model selection. Higher scores generally indicate better performance in that category.

**Available AI Models:**

For each model, consider its rate limit (RPM = requests per minute, req/day = requests per day), latency (time to respond), best uses, and example use cases.

{config.ABOUT_MODELS}

**Available Tools:**

Choose the fewest number of tools necessary to fulfill the user's request. Adding more tools can degrade model performance.

*   **FetchWebsite:** Retrieves text content from a given URL.
*   **Reminder:** Sets, cancels, etc reminders.
*   **SearchGrounding:** Provides access to online Google search.  **Important:** If you use this tool, do NOT use any other tools,\
only {config.SearchGroundingSuportedModels} suports SearchGrounding.
*   **ComputerTool:** Provides access to a sandboxed computer environment for code execution and file manipulation.

**Instructions:**

1.  Analyze the user's request to understand the requirements (e.g., reasoning, code processing, multimedia analysis, speed).
2.  Consider the benchmark scores to select a model that excels in the required capabilities.
3.  Select the most appropriate AI model based on its capabilities, rate limit, latency, and benchmark scores.
4.  Select the necessary tools. Prioritize using as few tools as possible. If `SearchGrounding` is sufficient, do not select any other tools.
5.  Output your decision in the following format:
"""
    ftools: list[types.Tool] = []
    for tool in tools:
        if tool == "FetchWebsite":
            ftools.append(FetchTool)
        elif tool == "Reminder":
            ftools.append(ReminderTool)
        elif tool == "SearchGrounding":
            if len(tools) != 1:
                raise Exception("Other tools along side SearchGrounding is not valid")
            if model not in config.SearchGroundingSuportedModels:
                raise Exception(f"Model {model} dont suport SearchGrounding")
            ftools.append(SearchGrounding)
        elif tool == "ComputerTool":
            ftools.append(ComputerTool)
        else:
            raise Exception("Unknown Tool passed: " + tool)
    return (config.Models[model].value, model in config.ToolSuportedModels, ftools)

def ModelSelector(
        model: Literal["Large20","Medium20","MediumThinking20","Small20","Large15","Medium15","Small15"],
    ) -> str:
    f"""\
Use this tool to choose the best AI model to respond to the user's request, considering the model capabilities, rate limits, latency, benchmark scores, and tool requirements.

If No tools want to provided then pass tools as empty list/array

**AI Model Benchmarks:**

Use these benchmarks to guide your model selection. Higher scores generally indicate better performance in that category.

**Available AI Models:**

For each model, consider its rate limit (RPM = requests per minute, req/day = requests per day), latency (time to respond), best uses, and example use cases.

{config.ABOUT_MODELS}

**Instructions:**

1.  Analyze the user's request to understand the requirements (e.g., reasoning, code processing, multimedia analysis, speed).
2.  Consider the benchmark scores to select a model that excels in the required capabilities.
3.  Select the most appropriate AI model based on its capabilities, rate limit, latency, and benchmark scores.
5.  Output your decision in the following format:
"""
    return config.Models[model].value

def ToolSelector(tools: list[Literal["FetchWebsite", "Reminder", "SearchGrounding", "ComputerTool"]]) -> list[types.Tool]:
    f"""\
Use this tool to choose which tools to should AI get accessed too.

If No tools want to provided then pass tools as empty list/array

**Available Tools:**

Choose the fewest number of tools necessary to fulfill the user's request. Adding more tools can degrade model performance.

*   **FetchWebsite:** Retrieves text content from a given URL.
*   **Reminder:** Sets, cancels, etc reminders.
*   **SearchGrounding:** Provides access to online Google search.  **Important:** If you use this tool, do NOT use any other tools
*   **ComputerTool:** Provides access to a sandboxed computer environment for code execution and file manipulation.

**Instructions:**

1.  Analyze the user's request to understand the requirements (e.g., reasoning, code processing, multimedia analysis, speed).
2.  Select the necessary tools. Prioritize using as few tools as possible.
3.  Output your decision in the following format:
"""
    ftools: list[types.Tool] = []
    for tool in tools:
        ftools.append(Tools[tool].value)
    return ftools
