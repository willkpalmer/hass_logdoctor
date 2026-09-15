"""Constants for the Log Doctor integration."""
from __future__ import annotations

DOMAIN = "log_doctor"
PLATFORMS = ["sensor", "button"]

STORAGE_VERSION = 1
STORAGE_KEY_PREFIX = "log_doctor"

DEFAULT_SCAN_HOUR = 8
DEFAULT_SCAN_MINUTE = 0
DEFAULT_LOOKBACK_HOURS = 24
DEFAULT_MIN_SEVERITY = "WARNING"
DEFAULT_MAX_GITHUB_QUERIES = 15
DEFAULT_GITHUB_CACHE_DAYS = 7
DEFAULT_REPORT_RETENTION_DAYS = 30

CONF_LOG_PATH = "log_path"
CONF_SCAN_TIME = "scan_time"
CONF_GITHUB_TOKEN = "github_token"
CONF_MOBILE_NOTIFY_SERVICE = "mobile_notify_service"
CONF_LOOKBACK_HOURS = "lookback_hours"
CONF_MIN_SEVERITY = "min_severity"
CONF_MAX_GITHUB_QUERIES = "max_github_queries"
CONF_ENABLE_GITHUB_LOOKUP = "enable_github_lookup"
CONF_REPORT_RETENTION_DAYS = "report_retention_days"

SEVERITY_LEVELS = ["WARNING", "ERROR", "CRITICAL"]
SEVERITY_ORDER = {"DEBUG": 0, "INFO": 1, "WARNING": 2, "ERROR": 3, "CRITICAL": 4}

SIGNAL_SCAN_COMPLETE = f"{DOMAIN}_scan_complete"

NOTIFICATION_ID = "log_doctor_daily_report"

SERVICE_SCAN_NOW = "scan_now"
SERVICE_CLEAR_HISTORY = "clear_history"

ATTR_ANOMALIES = "anomalies"
ATTR_NEW_COUNT = "new_count"
ATTR_RECURRING_COUNT = "recurring_count"
ATTR_LAST_SCAN = "last_scan"
ATTR_LAST_REPORT = "last_report"
ATTR_REPORT_FILE = "report_file"
ATTR_REPORTS_DIR = "reports_dir"

GITHUB_API_BASE = "https://api.github.com"
GITHUB_CORE_REPO = "home-assistant/core"

REPORTS_DIR_NAME = "log_doctor_reports"
LATEST_REPORT_FILENAME = "latest.md"
# Sensor attributes are stored in the state machine and recorder; keep the
# embedded report text bounded so a very large scan doesn't bloat either.
# The full, untruncated report is always on disk in REPORTS_DIR_NAME.
MAX_REPORT_ATTR_CHARS = 12000
