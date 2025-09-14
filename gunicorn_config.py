# gunicorn_config.py
import os

# --- Server Socket ---
# Bind to all network interfaces on port 8000
bind = os.environ.get("GUNICORN_BIND", "0.0.0.0:8000")

# --- Worker Processes ---
# IMPORTANT: Due to the file-based session management (`session.json`),
# we MUST use only one worker to prevent race conditions.
# If you switch to a process-safe state manager (like Redis), you can increase this.
workers = int(os.environ.get("GUNICORN_WORKERS", 1))
worker_class = "uvicorn.workers.UvicornWorker"

# --- Logging ---
# Log to stdout and stderr, which is standard for services managed by systemd
loglevel = os.environ.get("GUNICORN_LOGLEVEL", "info")
accesslog = "-"
errorlog = "-"

# --- Process Naming ---
# Helpful for identifying the process
proc_name = "bank-statement-converter"