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

# Gmail inbox panel (read-only, over IMAP). Credentials come from the k8s Secret:
# GMAIL_ADDRESS is the account; GMAIL_APP_PASSWORD is a Google "app password"
# (https://myaccount.google.com/apppasswords), not the normal login password.
# Leave them unset to hide the inbox panel.
GMAIL_ADDRESS = os.environ.get("GMAIL_ADDRESS", "")
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD", "")
IMAP_HOST = os.environ.get("IMAP_HOST", "imap.gmail.com")
INBOX_FETCH_COUNT = int(os.environ.get("INBOX_FETCH_COUNT", "8"))

# Today's-agenda panel: a Google Calendar "secret address in iCal format" URL
# (Calendar settings → Integrate calendar). Read-only, no OAuth. Blank = hidden.
CALENDAR_ICS_URL = os.environ.get("CALENDAR_ICS_URL", "")
AGENDA_DAYS = int(os.environ.get("AGENDA_DAYS", "7"))  # look-ahead window
AGENDA_MAX = int(os.environ.get("AGENDA_MAX", "15"))  # max events returned

# API spend meter: prices used to *estimate* cost from recorded token usage.
# Defaults are for Haiku 4.5 (USD per million tokens); override if they change.
CURRENCY_SYMBOL = os.environ.get("CURRENCY_SYMBOL", "$")
PRICE_INPUT_PER_MTOK = float(os.environ.get("PRICE_INPUT_PER_MTOK", "1.0"))
PRICE_OUTPUT_PER_MTOK = float(os.environ.get("PRICE_OUTPUT_PER_MTOK", "5.0"))
PRICE_WEB_SEARCH_PER_1K = float(os.environ.get("PRICE_WEB_SEARCH_PER_1K", "10.0"))
MAX_SPEND_RECORDS = int(os.environ.get("MAX_SPEND_RECORDS", "2000"))
