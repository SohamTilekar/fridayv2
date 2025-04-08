import enum
from google.genai import types
from typing import Literal
import config

from .reminder import CreateReminder, save_jobs, run_reminders, get_reminders, get_reminders_json, CancelReminder
from .webfetch import FetchWebsite
from .space import CodeExecutionEnvironment
from .imagen import Imagen
from .deepresearch import DeepResearch, DeepResearcher
from lschedule import CreateTask, UpdateTask

RunCommand = CodeExecutionEnvironment.RunCommand
RunCommandBackground = CodeExecutionEnvironment.RunCommandBackground
SendSTDIn = CodeExecutionEnvironment.SendSTDIn
GetSTDOut = CodeExecutionEnvironment.GetSTDOut
CreateFile = CodeExecutionEnvironment.CreateFile
CreateFolder = CodeExecutionEnvironment.CreateFolder
DeleteFile = CodeExecutionEnvironment.DeleteFile
DeleteFolder = CodeExecutionEnvironment.DeleteFolder
IsProcessRunning = CodeExecutionEnvironment.IsProcessRunning
KillProcess = CodeExecutionEnvironment.KillProcess
ReadFile = CodeExecutionEnvironment.ReadFile
WriteFile = CodeExecutionEnvironment.WriteFile
SendControlC = CodeExecutionEnvironment.SendControlC
LinkAttachment = CodeExecutionEnvironment.LinkAttachment

FetchTool = types.Tool(function_declarations=[
    types.FunctionDeclaration.from_callable_with_api_option(callable=FetchWebsite),
    types.FunctionDeclaration.from_callable_with_api_option(callable=DeepResearch),
])
ImagenTool = types.Tool(function_declarations=[types.FunctionDeclaration.from_callable_with_api_option(callable=Imagen)])
ReminderTool = types.Tool(function_declarations=[
    types.FunctionDeclaration.from_callable_with_api_option(callable=CreateReminder),
    types.FunctionDeclaration.from_callable_with_api_option(callable=CancelReminder),
    types.FunctionDeclaration.from_callable_with_api_option(callable=CreateTask),
    types.FunctionDeclaration.from_callable_with_api_option(callable=UpdateTask)
])
SearchGrounding = types.Tool(google_search=types.GoogleSearch())
ComputerTool = types.Tool(
    function_declarations=[
        types.FunctionDeclaration.from_callable_with_api_option(callable=CodeExecutionEnvironment.RunCommand),
        types.FunctionDeclaration.from_callable_with_api_option(callable=CodeExecutionEnvironment.RunCommandBackground),
        types.FunctionDeclaration.from_callable_with_api_option(callable=CodeExecutionEnvironment.SendSTDIn),
        types.FunctionDeclaration.from_callable_with_api_option(callable=CodeExecutionEnvironment.GetSTDOut),
        types.FunctionDeclaration.from_callable_with_api_option(callable=CodeExecutionEnvironment.CreateFile),
        types.FunctionDeclaration.from_callable_with_api_option(callable=CodeExecutionEnvironment.CreateFolder),
        types.FunctionDeclaration.from_callable_with_api_option(callable=CodeExecutionEnvironment.DeleteFile),
        types.FunctionDeclaration.from_callable_with_api_option(callable=CodeExecutionEnvironment.DeleteFolder),
        types.FunctionDeclaration.from_callable_with_api_option(callable=CodeExecutionEnvironment.IsProcessRunning),
        types.FunctionDeclaration.from_callable_with_api_option(callable=CodeExecutionEnvironment.KillProcess),
        types.FunctionDeclaration.from_callable_with_api_option(callable=CodeExecutionEnvironment.ReadFile),
        types.FunctionDeclaration.from_callable_with_api_option(callable=CodeExecutionEnvironment.WriteFile),
        types.FunctionDeclaration.from_callable_with_api_option(callable=CodeExecutionEnvironment.SendControlC),
        types.FunctionDeclaration.from_callable_with_api_option(callable=CodeExecutionEnvironment.LinkAttachment),
    ]
)

type ToolLiteral = Literal["Imagen", "FetchWebsite", "Reminder", "SearchGrounding", "ComputerTool"]

class Tools(enum.Enum):
    Imagen = ImagenTool
    FetchWebsite = FetchTool
    Reminder = ReminderTool
    ComputerTool = ComputerTool
    SearchGrounding = SearchGrounding
    @staticmethod
    def tool_names() -> list[Literal["Imagen", "FetchWebsite", "Reminder", "SearchGrounding", "ComputerTool"]]:
        return ["Imagen", "FetchWebsite", "Reminder", "SearchGrounding", "ComputerTool"]

def ModelAndToolSelector(
        model: Literal["Large25", "Large20","Medium20","MediumThinking20","Small20","Large15","Medium15","Small15"],
        tools: list[Literal["Imagen", "FetchWebsite", "Reminder", "SearchGrounding", "ComputerTool"]]
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
    return (config.Models[model].value, model in config.ToolSuportedModels and SearchGrounding not in ftools, ftools)

def ModelSelector(
        model: Literal["Large25", "Large20","Medium20","MediumThinking20","Small20","Large15","Medium15","Small15"],
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

def ToolSelector(tools: list[Literal["Imagen", "FetchWebsite", "Reminder", "SearchGrounding", "ComputerTool"]]) -> list[types.Tool]:
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
