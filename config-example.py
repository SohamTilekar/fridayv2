import enum

# Remove the -example part
GOOGLE_API = "Your-Google-API-Gose-Here"
# This is just if your self hosted option have multiple API keys for concrunt browsers
# RPM ( Request per minute limit, None for not any limit ), API key
FIRECRAWL_APIS = [(None, None)]
FIRECRAWL_ENDPOINT = (
    None  # None for firecrawl.dev hosted endpoint (FIRECRAWL_API requires if None)
)
AI_DIR = "~/friday/"

USR_NAME = "LastName FirstName"  # e.g Musk Elon
ABOUT_YOU = """\
"""
# this is example update it as your liking
# ABOUT_YOU = """
# - Profesion: XYZ
# - Age: 69
# - Country: XYZ
# """

MAX_RETRIES: int = 3
RETRY_DELAY: int | float = 1  # seconds

# Gemini AI's Only
MODEL_TOOL_SELECTOR = "gemini-2.0-flash-lite"


class Models(enum.Enum):
    Large25 = "gemini-2.5-pro-exp-03-25"
    MediumThinking25 = "gemini-2.5-flash-preview-04-17"
    Large20 = "gemini-2.0-pro-exp-02-05"
    MediumThinking20 = "gemini-2.0-flash-thinking-exp-01-21"
    Medium20 = "gemini-2.0-flash-001"
    Small20 = "gemini-2.0-flash-lite-001"
    Large15 = "gemini-1.5-pro-002"
    Medium15 = "gemini-1.5-flash-002"
    Small15 = "gemini-1.5-flash-8b-001"


model_RPM_map = {
    "gemini-2.5-pro-exp-03-25": 2,
    "gemini-2.5-flash-preview-04-17": 10,
    "gemini-2.0-pro-exp-02-05": 2,
    "gemini-2.0-flash-001": 15,
    "gemini-2.0-flash-thinking-exp-01-21": 10,
    "gemini-2.0-flash-lite-001": 30,
    "gemini-1.5-pro-002": 2,
    "gemini-1.5-flash-002": 15,
    "gemini-1.5-flash-8b-001": 15,
}

SearchGroundingSuportedModels = [
    Models.Large25.name,
    Models.MediumThinking25.name,
    Models.Large20.name,
    Models.Large15.name,
    Models.Medium20.name,
    Models.Medium15.name,
]
ToolSuportedModels = [
    Models.Large25.name,
    Models.MediumThinking25.name,
    Models.Large20.name,
    Models.Medium20.name,
    Models.Small20.name,
    Models.Large15.name,
    Models.Medium15.name,
    Models.Small15.name,
]
DynamicThinkingModels = [Models.MediumThinking25.name]
ModelsSet = [
    Models.Large25.name,
    Models.MediumThinking25.name,
    Models.Large20.name,
    Models.Medium20.name,
    Models.MediumThinking20.name,
    Models.Small20.name,
    Models.Large15.name,
    Models.Medium15.name,
    Models.Small15.name,
]

ABOUT_MODELS = """\
*   **Large25:**
    *   Rate Limit: 2 RPM, 50 req/day
    *   Latency: High
    *   Best For: Coding, Reasoning, Multimodal understanding, Native tool use
    *   Use Cases: Reason over complex problems, Tackle difficult code, math and STEM problems, Use the long context for analyzing large datasets, codebases or documents.
*   **MediumThinking25:**
    *   Rate Limit: 10 RPM, 500 req/day
    *   Latency: Medium
    *   Best For: Large scale processing (e.g. multiple pdfs), Low latency, high volume tasks which require thinking, Agentic use cases
    *   Use Cases: Reason over complex problems, Show the thinking process of the model, Call tools natively
*   **Large20:**
    *   Rate Limit: 2 RPM, 50 req/day
    *   Latency: High
    *   Best For: Multimodal understanding, Realtime streaming, Native tool use
    *   Use Cases: Processing large codebases (10,000+ lines), native tool calls (e.g., Search), streaming images/video.
*   **MediumThinking20:**
    *   Rate Limit: 10 RPM, 1500 req/day
    *   Latency: High
    *   Best For: Multimodal understanding, Reasoning, Coding
    *   Use Cases: Complex problem-solving, showing reasoning process, difficult code/math.
    *   **Important:** Dose not Suport any kind of tool calling
*   **Medium20:**
    *   Rate Limit: 15 RPM, 1500 req/day
    *   Latency: Medium
    *   Best For: Multimodal understanding, Realtime streaming, Native tool use
    *   Use Cases: Processing large codebases (10,000+ lines), native tool calls (e.g., Search), streaming images/video.
*   **Small20:**
    *   Rate Limit: 30 RPM, 1500 req/day
    *   Latency: Low
    *   Best For: Long Context, Realtime streaming, Native tool use
    *   Use Cases: Processing large codebases (10,000+ lines), native tool calls (e.g., Search), streaming images/video.
*   **Large15:**
    *   Rate Limit: 2 RPM, 50 req/day
    *   Latency: High
    *   Best For: Long Context, Complex Reasoning, Math Reasoning
    *   Use Cases: Reasoning over very large codebases (100k+ lines), synthesizing large amounts of text (e.g., 400 podcast transcripts).
*   **Medium15:**
    *   Rate Limit: 15 RPM, 1500 req/day
    *   Latency: Medium
    *   Best For: Image understanding, Video understanding, Audio understanding
    *   Use Cases: Processing large image sets (3,000 images), analyzing long videos (1 hour+), analyzing long audio files.
*   **Small15:**
    *   Rate Limit: 30 RPM, 1500 req/day
    *   Latency: Very Low
    *   Best For: Low latency, Multilingual, Summarization
    *   Use Cases: Realtime data transformation, realtime translation, summarizing large text (8 novels).
"""

CHAT_AI_TEMP: float = 0.2

if "Your-Google-API-Gose-Here" == GOOGLE_API:
    raise AssertionError("Set Your Google API first")
