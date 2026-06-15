"""Application configuration, sourced from environment variables."""
import os

from dotenv import load_dotenv

load_dotenv()

# Anthropic API key — read directly from the environment (.env in local dev).
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

# Model to use for every task. See the claude-api skill: opus-4-8 is the latest.
MODEL = os.environ.get("MODEL", "claude-opus-4-8")

# How often to refresh the answers, in hours. Defaults to every 6 hours.
REFRESH_HOURS = float(os.environ.get("REFRESH_HOURS", "6"))

# Where to persist run history. In Docker this is backed by a named volume.
DATA_DIR = os.environ.get("DATA_DIR", "./data")

# How many past runs to keep on disk / show in the dashboard.
MAX_RUNS = int(os.environ.get("MAX_RUNS", "50"))

# How many recent runs to feed back to Claude as anti-repeat context.
HISTORY_FEEDBACK = int(os.environ.get("HISTORY_FEEDBACK", "3"))

# How often the dashboard page auto-refreshes itself, in seconds.
PAGE_REFRESH_SECONDS = int(os.environ.get("PAGE_REFRESH_SECONDS", "300"))
