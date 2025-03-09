from google.genai import types
from typing import Literal

from .reminder import CreateReminder, save_jobs, run_reminders, get_reminders, CancelReminder
from .webfetch import FetchWebsite

FetchTool = types.Tool(function_declarations=[types.FunctionDeclaration.from_callable_with_api_option(callable=FetchWebsite, api_option="GEMINI_API")])
ReminderTool = types.Tool(function_declarations=[
    types.FunctionDeclaration.from_callable_with_api_option(callable=CreateReminder, api_option="GEMINI_API"),
    types.FunctionDeclaration.from_callable_with_api_option(callable=CancelReminder, api_option="GEMINI_API")
])
SearchGrounding = types.Tool(google_search=types.GoogleSearch())

def ModelAndToolSelector(
        model: Literal["Large2.0", "Medium2.0", "MediumThinking2.0", "Small2.0", "Large1.5", "Medium1.5", "Small1.5"],
        tools: list[Literal["FetchWebsite", "Reminder", "SearchGrounding"]]
    ) -> tuple[str, list[types.Tool]]:
    """\
Use this tool to choose the best AI model and tools to respond to the user's request, considering the model capabilities, rate limits, latency, benchmark scores, and tool requirements.

If No tools want to provided then pass tools as empty list/array

**AI Model Benchmarks:**

Use these benchmarks to guide your model selection. Higher scores generally indicate better performance in that category.

**Available AI Models:**

For each model, consider its rate limit (RPM = requests per minute, req/day = requests per day), latency (time to respond), best uses, and example use cases.

*   **Large2.0:**
    *   Rate Limit: 2 RPM, 50 req/day
    *   Latency: High
    *   Best For: Multimodal understanding, Realtime streaming, Native tool use
    *   Use Cases: Processing large codebases (10,000+ lines), native tool calls (e.g., Search), streaming images/video.
*   **MediumThinking2.0:**
    *   Rate Limit: 10 RPM, 1500 req/day
    *   Latency: High
    *   Best For: Multimodal understanding, Reasoning, Coding
    *   Use Cases: Complex problem-solving, showing reasoning process, difficult code/math.
*   **Medium2.0:**
    *   Rate Limit: 15 RPM, 1500 req/day
    *   Latency: Medium
    *   Best For: Multimodal understanding, Realtime streaming, Native tool use
    *   Use Cases: Processing large codebases (10,000+ lines), native tool calls (e.g., Search), streaming images/video.
*   **Small2.0:**
    *   Rate Limit: 30 RPM, 1500 req/day
    *   Latency: Low
    *   Best For: Long Context, Realtime streaming, Native tool use
    *   Use Cases: Processing large codebases (10,000+ lines), native tool calls (e.g., Search), streaming images/video.
*   **Large1.5:**
    *   Rate Limit: 2 RPM, 50 req/day
    *   Latency: High
    *   Best For: Long Context, Complex Reasoning, Math Reasoning
    *   Use Cases: Reasoning over very large codebases (100k+ lines), synthesizing large amounts of text (e.g., 400 podcast transcripts).
*   **Medium1.5:**
    *   Rate Limit: 15 RPM, 1500 req/day
    *   Latency: Medium
    *   Best For: Image understanding, Video understanding, Audio understanding
    *   Use Cases: Processing large image sets (3,000 images), analyzing long videos (1 hour+), analyzing long audio files.
*   **Small1.5:**
    *   Rate Limit: 30 RPM, 1500 req/day
    *   Latency: Very Low
    *   Best For: Low latency, Multilingual, Summarization
    *   Use Cases: Realtime data transformation, realtime translation, summarizing large text (8 novels).

**Available Tools:**

Choose the fewest number of tools necessary to fulfill the user's request. Adding more tools can degrade model performance.

*   **FetchWebsite:** Retrieves text content from a given URL.
*   **Reminder:** Sets, cancels, etc reminders.
*   **SearchGrounding:** Provides access to online Google search.  **Important:** If you use this tool, do NOT use any other tools.

**Instructions:**

1.  Analyze the user's request to understand the requirements (e.g., reasoning, code processing, multimedia analysis, speed).
2.  Consider the benchmark scores to select a model that excels in the required capabilities.
3.  Select the most appropriate AI model based on its capabilities, rate limit, latency, and benchmark scores.
4.  Select the necessary tools. Prioritize using as few tools as possible. If `SearchGrounding` is sufficient, do not select any other tools.
5.  Output your decision in the following format:
"""
    fmodel: str
    if model == "Large2.0":
        fmodel = "gemini-2.0-pro-exp-02-05"
    elif model == "MediumThinking2.0":
        fmodel = "gemini-2.0-flash-thinking-exp-01-21"
    elif model == "Medium2.0":
        fmodel = "gemini-2.0-flash-001"
    elif model == "Small2.0":
        fmodel = "gemini-2.0-flash-lite-001"
    elif model == "Large1.5":
        fmodel = "gemini-1.5-pro-002"
    elif model == "Medium1.5":
        fmodel = "gemini-1.5-flash-002"
    elif model == "Small1.5":
        fmodel = "gemini-1.5-flash-8b-001"
    else:
        raise Exception("Unknown Model passed: " + model)
    ftools: list[types.Tool] = []
    for tool in tools:
        if tool == "FetchWebsite":
            ftools.append(FetchTool)
        elif tool == "Reminder":
            ftools.append(ReminderTool)
        elif tool == "SearchGrounding":
            if len(tools) != 1:
                raise Exception("Other tools along side SearchGrounding is not valid")
            ftools.append(SearchGrounding)
        else:
            raise Exception("Unknown Tool passed: " + tool)
    return (fmodel, ftools)
