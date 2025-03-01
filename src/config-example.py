# Remove the -example part
GOOGLE_API: str = "Your-Google-API-Gose-Here"
DATA_DIR: str = "~/friday/"

YOUR_NAME: str = "LastName FirstName" #e.g Musk Elon
ABOUT_YOU: str = """\
"""
# this is example update it as your liking
# ABOUT_YOU: str = """
# - Profesion: XYZ
# - Age: 69
# - Country: XYZ
# """

MAX_RETRIES = 3
RETRY_DELAY = 1  # seconds

if("Your-Google-API-Gose-Here" == GOOGLE_API):
    raise AssertionError("Set Your Google API first")
