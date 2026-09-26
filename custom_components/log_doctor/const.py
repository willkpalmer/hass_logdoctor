"""Constants for the Log Doctor integration."""
from __future__ import annotations

DOMAIN = "log_doctor"
PLATFORMS = ["sensor", "button", "switch"]

DEVICE_NAME = "WP Log Doctor"

STORAGE_VERSION = 1
STORAGE_KEY_PREFIX = "log_doctor"

DEFAULT_SCAN_HOUR = 8
DEFAULT_SCAN_MINUTE = 0
DEFAULT_LOOKBACK_HOURS = 24
DEFAULT_MIN_SEVERITY = "WARNING"
DEFAULT_REPORT_RETENTION_DAYS = 30
DEFAULT_MAX_INVESTIGATED = 15

CONF_LOG_PATH = "log_path"
CONF_SCAN_TIME = "scan_time"
CONF_MOBILE_NOTIFY_SERVICE = "mobile_notify_service"
CONF_LOOKBACK_HOURS = "lookback_hours"
CONF_MIN_SEVERITY = "min_severity"
CONF_REPORT_RETENTION_DAYS = "report_retention_days"
CONF_INCLUDE_SUPERVISOR_LOGS = "include_supervisor_logs"
DEFAULT_INCLUDE_SUPERVISOR_LOGS = True
CONF_OPENAI_API_KEY = "openai_api_key"
CONF_MAX_INVESTIGATED = "max_investigated"
CONF_MONITOR_AUTOMATIONS = "monitor_automations"
DEFAULT_MONITOR_AUTOMATIONS = True
CONF_AUTOMATION_FAILURE_NOTIFY_DEVICE = "automation_failure_notify_device"
CONF_MONITOR_MISSED_SCHEDULES = "monitor_missed_schedules"
DEFAULT_MONITOR_MISSED_SCHEDULES = True
# Time pattern triggers repeating more often than this many minutes are left
# out of the missed schedule check (0 = check them all). 15 minutes skips
# the frequent polling-style patterns (every few minutes) that a restart of a
# couple of minutes would otherwise flag almost every time, while still
# covering quarter-hourly, hourly and less frequent schedules.
CONF_MISSED_SCHEDULE_MIN_PATTERN_MINUTES = "missed_schedule_min_pattern_minutes"
DEFAULT_MISSED_SCHEDULE_MIN_PATTERN_MINUTES = 15

# Supervisor's /logs endpoints default to only the last 100 lines unless a
# "lines" query parameter is passed. Max it out for now (Supervisor doesn't
# enforce an upper bound on this parameter).
SUPERVISOR_LOG_LINES = 1000

# Cap on how many raw log occurrences are printed per anomaly in the
# report, so one extremely noisy signature can't blow up the file.
MAX_LOG_ENTRIES_PER_ANOMALY = 20

SEVERITY_LEVELS = ["WARNING", "ERROR", "CRITICAL"]
SEVERITY_ORDER = {"DEBUG": 0, "INFO": 1, "WARNING": 2, "ERROR": 3, "CRITICAL": 4}

SIGNAL_SCAN_COMPLETE = f"{DOMAIN}_scan_complete"

NOTIFICATION_ID = "log_doctor_daily_report"
NOTIFICATION_ID_INVESTIGATION = "log_doctor_investigation_report"
# One notification per failing automation, suffixed with its object_id.
NOTIFICATION_ID_AUTOMATION_FAILURE_PREFIX = "log_doctor_automation_failure_"
NOTIFICATION_ID_MISSED_SCHEDULES = "log_doctor_missed_schedules"

SERVICE_SCAN_NOW = "scan_now"
SERVICE_CLEAR_HISTORY = "clear_history"

ATTR_ANOMALIES = "anomalies"
ATTR_NEW_COUNT = "new_count"
ATTR_RECURRING_COUNT = "recurring_count"
ATTR_LAST_SCAN = "last_scan"
ATTR_LAST_REPORT = "last_report"
ATTR_REPORT_FILE = "report_file"
ATTR_REPORTS_DIR = "reports_dir"

# <config>/logdoctor/ holds the automation failure log; the scheduled scan
# reviews go in its reviews/ subfolder (see paths.py).
LOGDOCTOR_DIR_NAME = "logdoctor"
REVIEWS_DIR_NAME = "reviews"
# Where everything lived before 0.15.0; migrated on startup.
LEGACY_REPORTS_DIR_NAME = "log_doctor_reports"
LATEST_REPORT_FILENAME = "latest.md"
LATEST_FINDINGS_FILENAME = "latest.findings.md"
FAILURE_LOG_FILENAME = "automation_failures.log"
# Sensor attributes are stored in the state machine and recorder; keep the
# embedded report text bounded so a very large scan doesn't bloat either.
# The full, untruncated report is always on disk in <config>/logdoctor/reviews/.
MAX_REPORT_ATTR_CHARS = 12000
