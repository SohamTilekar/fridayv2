# webfetch.py
from google.genai import types
from selenium import webdriver
from bs4 import BeautifulSoup
import requests
from urllib.parse import urljoin
import time
from PIL import Image
from io import BytesIO

# Supported image formats
SUPPORTED_MIME_TYPES = {"image/png", "image/jpeg", "image/webp", "image/heic", "image/heif"}

def fetch_with_retries(url: str, max_retries: int = 3, delay: float = 1.0) -> requests.Response | None:
    """Fetch a URL with retries in case of failure."""
    for attempt in range(max_retries):
        try:
            response = requests.get(url, timeout=5)  # Set a timeout to avoid long hangs
            if response.status_code == 200:
                return response
        except requests.RequestException as e:
            print(f"Attempt {attempt + 1} failed for {url}: {e}")
        time.sleep(delay)  # Wait before retrying
    print(f"Failed to load {url} after {max_retries} attempts.")
    return None

def FetchWebsite(url: str) -> str:
    # Initialize Selenium WebDriver
    options = webdriver.ChromeOptions()
    options.add_argument("--headless")  # Run in headless mode (no GUI)
    driver = webdriver.Chrome(options=options)

    driver.get(url)  # Use the passed URL

    # Get fully rendered HTML
    html = driver.page_source
    driver.quit()  # Close the browser

    # Parse with BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")
    return soup.get_text(separator=" ", strip=True)
