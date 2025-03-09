# webfetch.py
from selenium import webdriver
from bs4 import BeautifulSoup
from utils import retry

@retry()
def FetchWebsite(url: str) -> str:
    """Fetch a Text From a Given Website URL"""
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
