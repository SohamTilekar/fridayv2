import functools
import http.client
import ssl
import threading
import time
import traceback
import socket
from typing import Callable, Optional, ParamSpec, TypeVar

import google.auth.exceptions
import google.genai.errors
import googleapiclient.errors
import httplib2
import requests
import urllib3.connection

import config

R = TypeVar("R")
P = ParamSpec("P")


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
    google.genai.errors.ClientError
)

ignore_network_error: tuple[type[Exception], ...] = (
    BrokenPipeError,
    ssl.SSLWantReadError,
    ssl.SSLWantWriteError,
    ssl.SSLSyscallError,
    ssl.CertificateError,
)
