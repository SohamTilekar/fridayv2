import functools
import http.client
import ssl
import threading
import time
import traceback
import socket
from typing import Callable, Optional, ParamSpec, TypeVar, TypedDict, Any
from duckduckgo_search import DDGS
from duckduckgo_search.exceptions import DuckDuckGoSearchException
import google.auth.exceptions
import google.genai.errors
import googleapiclient.errors
import httplib2
import requests
import urllib3.connection
import httpx

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
    requests.exceptions.ReadTimeout,
    httpx.NetworkError
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
            self.api_calls: dict[str | None, int] = {api[1]: 0 for api in self.apis if api[1]}
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

    def _is_api_available(self, rpm_limit, api_key):
        """Check if an API is currently available based on concurrent and RPM limits."""
        if not api_key:
            return False

        # Check if API has credits
        if api_key not in self.api_credits or self.api_credits[api_key] <= 0:
            return False

        now = time.time()

        # Check if API is within RPM limit
        current_usage = self.api_calls[api_key]
        period_elapsed = now - self.api_reset_times.get(api_key, now)

        # Reset counter if period has elapsed
        if period_elapsed > 60:
            current_usage = 0
        elif rpm_limit and current_usage >= rpm_limit:
            return False

        # Check concurrent usage (against semaphore limit of 2)
        active_reqs = self.active_requests.get(api_key, 0)
        if active_reqs >= 2:  # Hardcoded semaphore limit from initialization
            return False

        return True

    def _get_best_api(self):
        """Get the best API from currently available APIs."""
        with self._lock:
            now = time.time()

            # First identify APIs to remove (0 credits)
            apis_to_remove = []
            for rpm_limit, api_key in self.apis:
                if api_key and api_key in self.api_credits and self.api_credits[api_key] <= 0:
                    apis_to_remove.append(api_key)

            # Remove dead APIs
            for api_key in apis_to_remove:
                self._remove_dead_api(api_key)

            # Filter for currently available APIs
            available_apis = []
            for rpm_limit, api_key in self.apis:
                if self._is_api_available(rpm_limit, api_key):
                    available_apis.append((rpm_limit, api_key))

            if not available_apis:
                return None, None

            # Now choose the best API from available ones
            best_api = None
            best_score = float('-inf')

            for rpm_limit, api_key in available_apis:
                # Available parameters for scoring
                credits = self.api_credits[api_key]

                # Get current parallel usage (active requests)
                active_reqs = self.active_requests.get(api_key, 0)

                # Calculate how long since last request (freshness)
                last_req_time = self.last_request_times.get(api_key, 0)
                time_since_last_req = now - last_req_time

                # Normalize active requests (0 is best, 2+ is worst)
                active_reqs_normalized = max(0, 2 - active_reqs) / 2

                # Normalize time since last request (cap at 5 seconds)
                freshness = min(time_since_last_req, 5) / 5

                # Simple score based primarily on credits and freshness
                score = (credits * 0.7) + (active_reqs_normalized * 0.15) + (freshness * 0.15)

                if score > best_score:
                    best_score = score
                    best_api = (rpm_limit, api_key)

            return best_api

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

                if api_key in self.api_credits:
                    self.api_credits[api_key] -= 1
                    if self.api_credits[api_key] <= 0:
                        self._remove_dead_api(api_key)

                response = requests.post(
                    endpoint,
                    json=request_params,
                    headers=headers,
                    timeout=timeout
                )

                # Handle successful response
                if response.status_code == 200:
                    data = response.json()
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
                    self.api_credits[api_key] += 1
                    self.api_calls[api_key] -= 1
                    return None
                elif response.status_code not in (408, 429):  # Don't count rate limit or timeout errors
                    self.api_credits[api_key] += 1
                    self.api_calls[api_key] -= 1
                    continue  # Retry immediately on timeout errors
                elif response.status_code == 500 and response.json().get("error").find("net::") != -1:
                    self.api_credits[api_key] += 1
                    self.api_calls[api_key] -= 1
                    return None
                self.api_credits[api_key] += 1
                self.api_calls[api_key] -= 1
                raise Exception("Unworth Status code return")
            except self.APICreditsOver:
                raise
            except requests.exceptions.ReadTimeout:
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

class DDGSearcher:
    _instance: Optional["DDGSearcher"] = None
    _lock = threading.Lock()
    _request_semaphore = threading.Semaphore(10)  # Limit concurrent requests
    _queue_lock = threading.Lock()  # Lock for queue operations

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(DDGSearcher, cls).__new__(cls)
            return cls._instance

    def __init__(self):
        if not hasattr(self, 'initialized'):
            self.ddg = DDGS(verify=False)

            # Backend state tracking
            self.backends = {
                'lite': {'available': True, 'backoff_until': 0},
                'html': {'available': True, 'backoff_until': 0}
            }

            # Fixed backoff time in seconds when rate limited
            self.backoff_time = 64

            # Request tracking
            self.last_request_time = 0
            self.min_request_interval = 1.0  # Minimum seconds between requests

            self.initialized = True

    def __call__(self, query: str, max_results: int | None = 10, **kwargs):
        with self._request_semaphore:
            # Wait if all backends are rate-limited
            if self._all_backends_limited():
                self._wait_for_backends()

            # First try with lite backend
            result = self._try_backend('lite', query, max_results, **kwargs)
            if result is not None:
                return result

            # If lite is rate-limited, try html backend
            result = self._try_backend('html', query, max_results, **kwargs)
            if result is not None:
                return result

            # If both are rate-limited, wait and retry once more
            self._wait_for_backends()
            return self(query, max_results, **kwargs)

    def _all_backends_limited(self) -> bool:
        """Check if all backends are currently rate-limited."""
        now = time.time()
        with self._lock:
            return all(not info['available'] and info['backoff_until'] > now
                      for info in self.backends.values())

    def _wait_for_backends(self):
        """Wait until at least one backend becomes available."""
        with self._lock:
            now = time.time()
            # Find the earliest time when any backend will become available
            min_backoff_time = min(info['backoff_until'] for info in self.backends.values())
            wait_time = max(0, min_backoff_time - now)

            if wait_time > 0:
                print(f"All backends rate-limited. Waiting {wait_time:.1f} seconds...")
                time.sleep(wait_time)

            # Reset availability for backends whose backoff period has expired
            now = time.time()
            for backend, info in self.backends.items():
                if info['backoff_until'] <= now:
                    info['available'] = True
                    print(f"Backend {backend} is now available")

    def _try_backend(self, backend: str, query: str, max_results: int | None, **kwargs):
        """Try to perform a search using the specified backend."""
        with self._lock:
            # Check if backend is available
            if not self.backends[backend]['available']:
                if self.backends[backend]['backoff_until'] <= time.time():
                    # Backoff period has expired, reset availability
                    self.backends[backend]['available'] = True
                    print(f"Backend {backend} is now available")
                else:
                    # Backend still in backoff period
                    return None

            # Apply rate limiting
            self._apply_rate_limiting()

        try:
            # Perform the search
            results = self.ddg.text(query, max_results=max_results, backend=backend, **kwargs)
            return results

        except DuckDuckGoSearchException as e:
            error_str = str(e)

            # Check if this is a rate limit error
            if any(domain in error_str for domain in [f"{backend}.duckduckgo.com", "duckduckgo.com"]):
                print(f"Rate limit hit for {backend} backend: {error_str}")

                with self._lock:
                    # Mark this backend as unavailable for the fixed backoff time
                    self.backends[backend]['available'] = False
                    self.backends[backend]['backoff_until'] = time.time() + self.backoff_time
                    print(f"Backend {backend} backed off for {self.backoff_time} seconds")

                return None
            else:
                # For non-rate-limit errors, pass them up
                raise

    def _apply_rate_limiting(self):
        """Apply minimum interval between requests."""
        now = time.time()
        time_since_last = now - self.last_request_time

        if time_since_last < self.min_request_interval:
            time.sleep(self.min_request_interval - time_since_last)

        self.last_request_time = time.time()

searcher = DDGSearcher()
