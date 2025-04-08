import time
import functools
import config
import traceback
from typing import Optional

def retry(max_retries: int | float = config.MAX_RETRIES, delay=config.RETRY_DELAY, exceptions: Optional[tuple]=None):
    """
    A decorator that retries a function up to `max_retries` times with exponential backoff.

    Args:
        max_retries: The maximum number of times to retry the function.
        delay: The initial delay (in seconds) between retries. The delay doubles with each retry.
        exceptions: A tuple of exception types to catch and retry on. If None, catches all exceptions.
    """
    def decorator_retry(func):
        @functools.wraps(func)
        def wrapper_retry(*args, **kwargs):
            attempt = 0
            while attempt < max_retries:
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    # Only retry on specified exceptions, or all exceptions if None
                    if exceptions is not None and not isinstance(e, exceptions):
                        print(f"Exception {type(e).__name__} not in retry list for {func.__name__}. Raising.")
                        traceback.print_exc()
                        raise  # Re-raise exceptions we don't want to retry on

                    print(f"Attempt {attempt + 1} failed: {e}, retrying...")

                    if attempt < max_retries - 1:
                        # Calculate backoff time
                        backoff_time = min(delay * (2 ** attempt), 128)
                        print(f"Waiting {backoff_time:.2f} seconds before next attempt...")
                        time.sleep(backoff_time)  # Exponential backoff
                    else:
                        print(f"Max retries ({max_retries}) reached for {func.__name__}. Raising exception.")
                        traceback.print_exc()
                        raise  # Re-raise the exception

                attempt += 1
            raise

        return wrapper_retry
    return decorator_retry
