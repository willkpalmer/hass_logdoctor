"""Log messages about an integration failing to set up.

Home Assistant logs these through its own loggers rather than the
integration's, so they don't look like the integration's at first glance:

- homeassistant.setup: "Setup failed for 'x': Integration failed to
  initialize." (and "custom integration 'x'"), "Unable to set up
  dependencies of 'x'", "Error during setup of component x"
- homeassistant.config_entries: "Error setting up entry <title> for x",
  "Config entry '<title>' for x integration not ready yet: ...",
  "... could not authenticate", "Migration handler not found for entry
  <title> for x"
- the entity component's own logger (homeassistant.components.sensor, ...):
  "Error while setting up x platform for sensor", "Platform x not ready
  yet", "Setup of platform x is taking longer than ..."

setup_failure_domain() picks out the integration such a message is about,
so the Log review can mark it a setup failure and keep it there (it's a
fault, not just noise from starting up), and the Devices & integrations
check can list it under the integration's problem (see health_monitor.py).
"""
from __future__ import annotations

import re

_PATTERNS: list[tuple[str | None, re.Pattern[str]]] = [
    ("homeassistant.setup", re.compile(r"Setup failed for (?:custom integration )?'(?P<d>[\w]+)'")),
    ("homeassistant.setup", re.compile(r"Unable to set up dependencies of '(?P<d>[\w]+)'")),
    ("homeassistant.setup", re.compile(r"Error during setup of component (?P<d>[\w]+)")),
    ("homeassistant.config_entries", re.compile(r"Error setting up entry .* for (?P<d>[\w]+)")),
    ("homeassistant.config_entries", re.compile(r"Config entry '.*' for (?P<d>[\w]+) integration (?:not ready yet|could not authenticate)")),
    ("homeassistant.config_entries", re.compile(r"Migration handler not found for entry .* for (?P<d>[\w]+)")),
    (None, re.compile(r"Error while setting up (?P<d>[\w]+) platform for \w+")),
    (None, re.compile(r"Platform (?P<d>[\w]+) not (?:ready yet|connected yet)")),
    (None, re.compile(r"Setup of platform (?P<d>[\w]+) is taking longer than")),
    (None, re.compile(r"(?P<d>[\w]+) raises exception \w+ in forwarded platform")),
]


def setup_failure_domain(logger: str, message: str) -> str | None:
    """The integration a setup failure message is about, or None."""
    first_line = message.split("\n", 1)[0]
    for wanted_logger, pattern in _PATTERNS:
        if wanted_logger is not None and logger != wanted_logger:
            continue
        if wanted_logger is None and not logger.startswith("homeassistant."):
            continue
        if match := pattern.search(first_line):
            return match.group("d")
    return None
