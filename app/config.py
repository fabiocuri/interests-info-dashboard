"""Application configuration, sourced from environment variables."""
import os

from dotenv import load_dotenv

load_dotenv()

# Anthropic API key — read directly from the environment (.env in local dev).
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

# Model. Default to the cheapest tier (Haiku 4.5) to minimise cost per run.
MODEL = os.environ.get("MODEL", "claude-haiku-4-5")

# Hard cap on output tokens per task — answers are short (≤2 paragraphs / 10 lines).
MAX_OUTPUT_TOKENS = int(os.environ.get("MAX_OUTPUT_TOKENS", "600"))

# Cap web searches for the one task that needs live info, to bound search cost.
WEB_SEARCH_MAX_USES = int(os.environ.get("WEB_SEARCH_MAX_USES", "2"))

# Where to persist run history. In k8s this is backed by a PVC.
DATA_DIR = os.environ.get("DATA_DIR", "./data")

# How many past runs to keep on disk / show in the dashboard.
MAX_RUNS = int(os.environ.get("MAX_RUNS", "50"))

# Recent answers per task fed back for anti-repeat. 1 keeps input tokens low.
HISTORY_FEEDBACK = int(os.environ.get("HISTORY_FEEDBACK", "1"))
