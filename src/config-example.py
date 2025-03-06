import pathlib

# Remove the -example part
GOOGLE_API: str = "Your-Google-API-Gose-Here"
AI_DIR: pathlib.Path = pathlib.Path("~/friday/")

YOUR_NAME: str = "LastName FirstName" #e.g Musk Elon
ABOUT_YOU: str = """\
"""
# this is example update it as your liking
# ABOUT_YOU: str = """
# - Profesion: XYZ
# - Age: 69
# - Country: XYZ
# """

MAX_RETRIES: int = 3
RETRY_DELAY: int | float = 1  # seconds

# Gemini AI's Only
CHAT_AI: str = "gemini-2.0-flash"
MAX_OUTPUT_TOKEN_LIMIT: int = 8192 # For gemini it is curently caped`8192`
TOKEN_REDUCER_PLANER: str = "gemini-2.0-flash"
SUMMARIZER_AI: str = "gemini-2.0-flash-lite"

if("Your-Google-API-Gose-Here" == GOOGLE_API):
    raise AssertionError("Set Your Google API first")
