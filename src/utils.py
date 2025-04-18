import functools
import http.client
import ssl
import threading
import time
import traceback
import socket
from typing import Callable, Optional, ParamSpec, TypeVar, TypedDict, Any, cast

import google.auth.exceptions
import google.genai.errors
import googleapiclient.errors
import httplib2
import requests
import urllib3.connection

import config

R = TypeVar("R")
P = ParamSpec("P")

network_errors: tuple[type[Exception], ...] = (
    # Built-in exceptions
    ConnectionError,  # Base class for connection-related errors
    TimeoutError,  # Can be raised during network ops (e.g., socket timeouts)
    # socket module
    socket.timeout,
    socket.error,
    socket.gaierror,
    socket.herror,
    # ssl module
    ssl.SSLError,
    # http.client module
    http.client.HTTPException,
    http.client.NotConnected,
    http.client.IncompleteRead,
    http.client.BadStatusLine,
    http.client.RemoteDisconnected,
    # urllib3 exceptions
    urllib3.exceptions.HTTPError,
    urllib3.exceptions.NewConnectionError,
    urllib3.exceptions.MaxRetryError,
    urllib3.exceptions.ConnectTimeoutError,
    urllib3.exceptions.ReadTimeoutError,
    urllib3.exceptions.SSLError,
    # requests exceptions (wraps urllib3)
    requests.exceptions.RequestException,
    requests.exceptions.ConnectionError,
    requests.exceptions.HTTPError,
    requests.exceptions.Timeout,
    requests.exceptions.TooManyRedirects,
    requests.exceptions.SSLError,
    # httplib2 errors
    httplib2.ServerNotFoundError,
    httplib2.RedirectLimit,
    httplib2.ProxiesUnavailableError,
    # google-auth errors
    google.auth.exceptions.TransportError,
    google.auth.exceptions.TimeoutError,
    google.auth.exceptions.ResponseError,
    # googleapiclient errors
    googleapiclient.errors.HttpError,
    googleapiclient.errors.ResumableUploadError,
    # genai
    google.genai.errors.ServerError,
    google.genai.errors.ClientError,
    requests.exceptions.ReadTimeout
)

ignore_network_error: tuple[type[Exception], ...] = (
    BrokenPipeError,
    ssl.SSLWantReadError,
    ssl.SSLWantWriteError,
    ssl.SSLSyscallError,
    ssl.CertificateError,
)


def retry(
    max_retries: int | float = config.MAX_RETRIES,
    delay=config.RETRY_DELAY,
    exceptions: tuple[type[Exception], ...] = (),
    ignore_exceptions: tuple[type[Exception], ...] = (),
):
    """
    A decorator that retries a function with flexible handling for specific exceptions.

    Retries occur under these conditions:
    1. If `exceptions` is provided:
       - Retries indefinitely (or until success) for exceptions listed in `exceptions`, without counting towards `max_retries`.
       - Retries up to `max_retries` times for exceptions *not* listed in `exceptions`, counting each towards the limit.
    2. If `exceptions` is empty:
       - Retries up to `max_retries` times for *any* exception, counting each towards the limit.

    Uses exponential backoff. The backoff duration increases based on the number of *counted* retry attempts.
    For exceptions specified in the `exceptions` tuple, the backoff time uses the delay associated with the *last counted* attempt.

    Args:
        max_retries: Max number of *counted* retries (for exceptions not in `exceptions`, or all if `exceptions` is empty). Use float('inf') for unlimited counted retries.
        delay: Initial delay (seconds) between retries. Doubles with each *counted* retry.
        exceptions: Tuple of exception types to retry without counting against `max_retries`.
    """

    def decorator_retry(func: Callable[P, R]) -> Callable[P, R]:
        @functools.wraps(func)
        def wrapper_retry(*args: P.args, **kwargs: P.kwargs) -> R:
            attempt = 0  # Number of *counted* attempts
            back_off = 0.5
            while attempt < max_retries:
                back_off *= 2
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    should_increment_attempt = False
                    should_ignore_and_retry = False

                    if exceptions:  # Specific exceptions provided
                        if isinstance(e, exceptions) and not isinstance(
                            e, ignore_exceptions
                        ):
                            # It's an exception we ignore for counting purposes but still retry
                            print(
                                f"Attempt failed with ignored exception {type(e).__name__}: {e}. Retrying (attempt count {attempt} remains unchanged)..."
                            )
                            should_ignore_and_retry = True
                        else:
                            # It's an exception we count
                            print(
                                f"Attempt {attempt + 1} failed with counted exception {type(e).__name__}: {e}. Retrying..."
                            )
                            should_increment_attempt = True
                    else:  # No specific exceptions, count all
                        print(f"Attempt {attempt + 1} failed: {e}. Retrying...")
                        should_increment_attempt = True

                    # Decide on action based on flags
                    if should_increment_attempt:
                        attempt += 1
                        if attempt >= max_retries:
                            print(
                                f"Max counted retries ({max_retries}) reached for {func.__name__}. Raising exception."
                            )
                            traceback.print_exc()
                            raise e  # Re-raise the last counted exception

                        # Calculate backoff based on *new* counted attempts
                        # Use attempt-1 because attempt was just incremented
                        backoff_time = min(delay * (back_off), 128)
                        print(
                            f"Waiting {backoff_time:.2f} seconds before next attempt..."
                        )
                        time.sleep(backoff_time)

                    elif should_ignore_and_retry:
                        # Calculate backoff based on the *current* number of counted attempts (or initial delay if 0)
                        # This prevents rapid retries for ignored exceptions but doesn't escalate delay based on them.
                        backoff_time = min(delay * (back_off), 128)
                        print(
                            f"Waiting {backoff_time:.2f} seconds before next attempt (ignored exception)..."
                        )
                        time.sleep(backoff_time)
                    else:
                        # This state should not be reachable given the logic above.
                        # If an exception occurs, either `exceptions` is empty (increment=True),
                        # or `exceptions` is provided and `e` is in it (ignore=True),v
                        # or `exceptions` is provided and `e` is not in it (increment=True).
                        # If reached, raise the original error to avoid silent failure/infinite loop.
                        print(
                            f"Internal retry logic error for exception {type(e).__name__}. Raising."
                        )
                        traceback.print_exc()
                        raise e
            # If the loop finishes because attempt >= max_retries, the exception was raised inside.
            # If max_retries is 0, the loop never runs. Function might return None implicitly.
            # If max_retries is inf, the loop only exits via return or an unhandled exception (already raised).
            raise RuntimeError("Unreachable code reached")  # just for type checker

        return wrapper_retry

    return decorator_retry


class FetchLimiter:
    """
    A class to limit the number of function calls within a specific time period,
    using a semaphore to limit concurrent requests and a lock to ensure thread safety.

    This class implements a rate limiter that controls the number of calls to a decorated function.
    It uses a singleton pattern to ensure only one instance exists, managing call counts and reset times.
    """

    _instance: Optional["FetchLimiter"] = None
    _lock: threading.Lock = threading.Lock()
    _semaphore: threading.Semaphore = threading.Semaphore(
        2
    )  # Limit to 2 concurrent requests
    calls: int = 0
    period: int = 60  # seconds
    max_calls: int = 10
    last_reset: float = 0.0

    def __new__(cls) -> "FetchLimiter":
        """
        Implements the singleton pattern, ensuring only one instance of FetchLimiter exists.
        """
        with cls._lock:
            if not cls._instance:
                cls._instance = super().__new__(cls)
                cls._instance.last_reset = time.time()
            return cls._instance

    def __call__(self, func: Callable[P, R]) -> Callable[P, R | None]:
        """
        Wraps the given function to limit its execution rate.

        Args:
            func: The function to be rate-limited.

        Returns:
            A wrapped function that adheres to the rate limits.
        """

        @functools.wraps(func)
        def limited_func(*args: P.args, **kwargs: P.kwargs) -> R | None:
            """
            The wrapped function that enforces the rate limits.
            """
            with self._semaphore:  # Acquire semaphore to limit concurrent requests
                with self._lock:
                    now = time.time()
                    # Reset the call count if the period has elapsed
                    if now - self.last_reset > self.period:
                        self.calls = 0
                        self.last_reset = now

                    # Wait if the maximum number of calls has been reached
                    while self.calls >= self.max_calls:
                        sleep_time = self.last_reset + self.period - now
                        if sleep_time > 0:
                            time.sleep(sleep_time)
                        now = time.time()
                        if now - self.last_reset > self.period:
                            self.calls = 0
                            self.last_reset = now

                    self.calls += 1
                try:
                    return func(*args, **kwargs)
                except requests.exceptions.HTTPError as e:
                    print(*args, {**kwargs})
                    traceback.print_exc()
                    print(e)
                    print(e.response.json())
                    print("-------------------------------")
                    if e.response.json()["error"].startswith("This website is no longer supported"):
                        return None
                finally:
                    pass

        return limited_func



class ScrapedMetadata(TypedDict, total=False):
    title: str
    ogTitle: str
    language: str
    ogDescription: str
    viewport: str
    favicon: str
    ogUrl: str
    ogImage: str
    ogLocale: str
    description: str
    scrapeId: str
    sourceURL: str
    url: str
    statusCode: int
    error: Optional[str]

class ScrapedData(TypedDict):
    markdown: str
    links: list[str]
    metadata: ScrapedMetadata
    html: Optional[str]
    rawHtml: Optional[str]
    screenshot: Optional[str]
    actions: Optional[dict[str, Any]]
    llm_extraction: Optional[dict[str, Any]]
    warning: Optional[str]
    changeTracking: Optional[dict[str, Any]]
    url_display_info: dict[str, str]

class FireFetcher:
    class APICreditsOver(Exception):
        ...
    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(FireFetcher, cls).__new__(cls)
            return cls._instance

    def __init__(self):
        if not hasattr(self, 'initialized'):
            self.apis = config.FIRECRAWL_APIS
            self.api_semaphores = {api[1]: threading.Semaphore(2) for api in self.apis if api[1]}
            self.api_calls = {api[1]: 0 for api in self.apis if api[1]}
            self.api_reset_times = {api[1]: time.time() for api in self.apis if api[1]}
            self.api_credits = {}
            self.api_index = 0
            # Track when each API was last used
            self.last_request_times = {api[1]: 0. for api in self.apis if api[1]}
            # Track current active requests per API
            self.active_requests = {api[1]: 0 for api in self.apis if api[1]}
            self.initialized = True

            # Initialize API credits
            self._initialize_api_credits()
        if not self.apis:
            raise ValueError("No Firecrawl APIs configured")
        print(self.api_credits)

    def _initialize_api_credits(self):
        """Initialize the credit count for each API key."""
        for rpm_limit, api_key in self.apis:
            if api_key:
                self.api_credits[api_key] = self._check_credits(api_key)

    @retry(exceptions=network_errors, ignore_exceptions=ignore_network_error)
    def _check_credits(self, api_key: str) -> int:
        """Check how many credits an API key has."""
        if not api_key:
            return 0

        url = f"{config.FIRECRAWL_ENDPOINT or "http://api.firecrawl.dev"}/v1/team/credit-usage"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }

        response = requests.get(url, headers=headers, timeout=15)
        if response.status_code == 200:
            data = response.json()
            if data.get("success", False):
                return data.get("data", {}).get("remaining_credits", 0)
        print(response.json())
        raise requests.exceptions.HTTPError(f"HTTP {response.status_code}")

    @retry(exceptions=(APICreditsOver,))
    def __call__(self, url: str, params: dict[str, Any]) -> Optional[ScrapedData]:
        # Select best API based on credits and usage
        api_info = self._get_best_api()
        if not api_info:
            print("No API keys with credits available")
            return None

        rpm_limit, api_key = api_info

        if not api_key:
            return self._make_request(url, params, None)

        with self._lock:
            self.active_requests[api_key] += 1

        try:
            with self.api_semaphores[api_key]:
                with self._lock:
                    now = time.time()
                    # Update the last request time
                    self.last_request_times[api_key] = now

                    if now - self.api_reset_times[api_key] > 60:
                        self.api_calls[api_key] = 0
                        self.api_reset_times[api_key] = now

                    if rpm_limit and self.api_calls[api_key] >= rpm_limit:
                        wait_time = 60 - (now - self.api_reset_times[api_key])
                        if wait_time > 0:
                            time.sleep(wait_time)
                        self.api_calls[api_key] = 0
                        self.api_reset_times[api_key] = time.time()

                    self.api_calls[api_key] += 1

                return self._make_request(url, params, api_key)
        finally:
            with self._lock:
                if api_key in self.active_requests:
                    self.active_requests[api_key] -= 1

    def _get_best_api(self):
        """Get the best API based on credits, usage rate, parallel usage, and last request time."""
        with self._lock:
            best_api = None
            best_score = float('-inf')
            now = time.time()

            # Track which APIs to remove due to 0 credits
            apis_to_remove = []

            for rpm_limit, api_key in self.apis:
                if not api_key:
                    continue

                if api_key not in self.api_credits or self.api_credits[api_key] <= 0:
                    # Mark this API for removal if it has 0 or no credits
                    if api_key in self.api_credits and self.api_credits[api_key] <= 0:
                        apis_to_remove.append(api_key)
                    continue

                # Available parameters for scoring
                credits = self.api_credits[api_key]
                current_usage = self.api_calls[api_key]

                # Get current parallel usage (active requests)
                active_reqs = self.active_requests.get(api_key, 0)

                # Calculate how long since last request (freshness)
                last_req_time = self.last_request_times.get(api_key, 0)
                time_since_last_req = now - last_req_time

                # Calculate estimated capacity based on rpm limit and current period
                period_elapsed = now - self.api_reset_times.get(api_key, now)
                period_remaining = max(0, 60 - period_elapsed)

                # Max capacity calculation
                if rpm_limit is None:
                    # No rate limit, just use a high number
                    capacity_score = 1000
                else:
                    # How many more requests we could make in this period
                    # Taking into account time remaining in the period
                    capacity_score = rpm_limit - current_usage
                    if period_remaining < 1:  # Almost end of period
                        capacity_score = rpm_limit  # We'll reset soon

                # Combine all factors into a comprehensive score
                # 1. Credits (most important) - weighted at 60%
                # 2. Available capacity - weighted at 15%
                # 3. Active requests (fewer is better) - weighted at 15%
                # 4. Time since last request (longer is better) - weighted at 10%

                # Normalize active requests (0 is best, 2+ is worst)
                active_reqs_normalized = max(0, 2 - active_reqs) / 2

                # Normalize time since last request (cap at 5 seconds)
                freshness = min(time_since_last_req, 5) / 5

                score = (
                    (credits * 0.6) +
                    (capacity_score * 0.15) +
                    (active_reqs_normalized * 0.15) +
                    (freshness * 0.1)
                )

                if score > best_score:
                    best_score = score
                    best_api = (rpm_limit, api_key)

            # Remove any dead APIs with 0 credits
            for api_key in apis_to_remove:
                self._remove_dead_api(api_key)

            return best_api if best_api else (None, None)

    def _remove_dead_api(self, api_key: str | None):
        """Remove an API key with no credits from the list of available APIs."""
        print(f"API key {api_key} is dead (no credits). Removing from rotation.")
        with self._lock:
            if api_key in self.api_credits:
                del self.api_credits[api_key]

            if api_key in self.api_semaphores:
                del self.api_semaphores[api_key]
            if api_key in self.api_calls:
                del self.api_calls[api_key]
            if api_key in self.api_reset_times:
                del self.api_reset_times[api_key]
            if api_key in self.last_request_times:
                del self.last_request_times[api_key]
            if api_key in self.active_requests:
                del self.active_requests[api_key]

            self.apis = [(rpm, key) for rpm, key in self.apis if key != api_key]
            if not self.apis:
                print("WARNING: No API keys with credits remaining!")

    def _make_request(self, url: str, request_params: dict[str, Any], api_key: Optional[str] = None) -> Optional[ScrapedData]:
        request_params["url"] = url
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        endpoint = f"{config.FIRECRAWL_ENDPOINT or 'http://api.firecrawl.dev'}/v1/scrape"

        attempt = 0
        back_off = 1
        while attempt < config.MAX_RETRIES:
            try:
                # Add buffer time to timeout
                timeout = request_params.get("timeout", None)
                if timeout:
                    timeout += 10_000

                response = requests.post(
                    endpoint,
                    json=request_params,
                    headers=headers,
                    timeout=timeout
                )

                # Handle successful response
                if response.status_code == 200:
                    data = response.json()
                    if data.get("success") and "data" in data:
                        with self._lock:
                            if api_key in self.api_credits:
                                self.api_credits[api_key] -= 1
                                if self.api_credits[api_key] <= 0:
                                    self._remove_dead_api(api_key)
                    return data["data"]

                # Log response info
                print(url, response, response.json())

                # Handle various status codes
                if response.status_code == 402:
                    if api_key:
                        print(f"Payment required: API key {api_key} has no credits")
                        self._remove_dead_api(api_key)
                    raise self.APICreditsOver("API has no credits")
                elif response.status_code == 403:
                    return None
                elif response.status_code == 500 and ((response.json().get("error") or "").find("timeout") > 0):
                    continue  # Retry immediately on timeout errors
                elif response.status_code not in (408, 429):  # Don't count rate limit or timeout errors
                    attempt += 1

                # Apply backoff
                back_off *= 2
                time.sleep(min(config.RETRY_DELAY * back_off, 128))
            except self.APICreditsOver:
                raise
            except requests.exceptions.ReadTimeout:
                with self._lock:
                    if api_key in self.api_credits:
                        self.api_credits[api_key] -= 1
                        if self.api_credits[api_key] <= 0:
                            self._remove_dead_api(api_key)
                back_off *= 2
                time.sleep(min(config.RETRY_DELAY * back_off, 128))
                continue
            except Exception as e:
                # Handle network errors differently
                if isinstance(e, network_errors) and not isinstance(e, ignore_network_error):
                    back_off *= 2
                    time.sleep(min(config.RETRY_DELAY * back_off, 128))
                    continue

                # For other exceptions, count the attempt
                attempt += 1
                back_off *= 2
                time.sleep(min(config.RETRY_DELAY * back_off, 128))

        raise  # Max retries exceeded

scrape_url = FireFetcher()
