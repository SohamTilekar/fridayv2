import enum
from google.genai import types
from typing import Literal
import config

from .reminder import CreateReminder, save_jobs, run_reminders, get_reminders, CancelReminder
from .webfetch import FetchWebsite

FetchTool = types.Tool(function_declarations=[types.FunctionDeclaration.from_callable_with_api_option(callable=FetchWebsite, api_option="GEMINI_API")])
ReminderTool = types.Tool(function_declarations=[
    types.FunctionDeclaration.from_callable_with_api_option(callable=CreateReminder, api_option="GEMINI_API"),
    types.FunctionDeclaration.from_callable_with_api_option(callable=CancelReminder, api_option="GEMINI_API")
])
SearchGrounding = types.Tool(google_search=types.GoogleSearch())

type ToolLiteral = Literal["FetchWebsite", "Reminder", "SearchGrounding"]

class Tools(enum.Enum):
    FetchWebsite = FetchTool
    Reminder = ReminderTool
    SearchGrounding = SearchGrounding
    @staticmethod
    def tool_names() -> list[Literal["FetchWebsite", "Reminder", "SearchGrounding"]]:
        return ["FetchWebsite", "Reminder", "SearchGrounding"]

def ModelAndToolSelector(
        model: Literal["Large20","Medium20","MediumThinking20","Small20","Large15","Medium15","Small15"],
        tools: list[Literal["FetchWebsite", "Reminder", "SearchGrounding"]]
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

def ToolSelector(tools: list[Literal["FetchWebsite", "Reminder", "SearchGrounding"]]) -> list[types.Tool]:
    f"""\
Use this tool to choose which tools to should AI get accessed too.

If No tools want to provided then pass tools as empty list/array

**Available Tools:**

Choose the fewest number of tools necessary to fulfill the user's request. Adding more tools can degrade model performance.

*   **FetchWebsite:** Retrieves text content from a given URL.
*   **Reminder:** Sets, cancels, etc reminders.
*   **SearchGrounding:** Provides access to online Google search.  **Important:** If you use this tool, do NOT use any other tools

**Instructions:**

1.  Analyze the user's request to understand the requirements (e.g., reasoning, code processing, multimedia analysis, speed).
2.  Select the necessary tools. Prioritize using as few tools as possible.
3.  Output your decision in the following format:
"""
    ftools: list[types.Tool] = []
    for tool in tools:
        ftools.append(Tools[tool].value)
    return ftools

