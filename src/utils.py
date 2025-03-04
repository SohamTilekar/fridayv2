import time
import functools
import config

def retry(max_retries=config.MAX_RETRIES, delay=config.RETRY_DELAY):
    """
    A decorator that retries a function up to `max_retries` times with exponential backoff.

    Args:
        max_retries: The maximum number of times to retry the function.
        delay: The initial delay (in seconds) between retries.  The delay doubles with each retry.
    """
    def decorator_retry(func):
        @functools.wraps(func)
        def wrapper_retry(*args, **kwargs):
            attempt = 0
            while attempt < max_retries:
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    print(f"Attempt {attempt + 1} failed: {e}, retrying...")
                    if attempt < max_retries - 1:
                        time.sleep(delay * (2 ** attempt))  # Exponential backoff
                    else:
                        print(f"Max retries reached for {func.__name__}.  Raising exception.")
                        raise  # Re-raise the exception
                attempt += 1
            return None # Should not reach here if exception is raised
        return wrapper_retry
    return decorator_retry
