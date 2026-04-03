from collections import deque
from datetime import datetime, timezone, timedelta

# Global log buffer shared across modules
app_logs = deque(maxlen=100)

def log_message(msg):
    """Adds a timestamped message to the log buffer."""
    # timezone use taipei (GMT+8)
    timestamp = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S")
    app_logs.appendleft(f"[{timestamp}] {msg}")
    # write to file as well
    with open("log.txt", "a") as f:
        f.write(f"[{timestamp}] {msg}\n")
