import json
import time


def sleep_timer(seconds: float) -> str:
    """
    Pauses execution for a specified duration synchronously.

    This tool is useful for introducing a wait period. Note that while
    the tool is sleeping, it will not block other server operations.

    Args:
        seconds (float): The number of seconds to sleep.
    """
    start_time = time.time()
    time.sleep(seconds)
    end_time = time.time()
    actual_duration = end_time - start_time

    return json.dumps(
        {
            "success": True,
            "requested_seconds": seconds,
            "actual_seconds": round(actual_duration, 4),
            "status": "completed",
        }
    )
