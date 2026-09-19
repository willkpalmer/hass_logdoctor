"""The investigation stage: automatically research a freshly written scan
report with an OpenAI model, run right after each scan.

This mirrors what the standalone companion app (see companion/) does by
hand, on demand, against any report file - but runs automatically here,
against the report the scan that just ran wrote to disk, using an API key
configured on the integration itself rather than an environment variable.
The two are independent; either can be used without the other.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

import openai
from openai import AsyncOpenAI

from homeassistant.core import HomeAssistant

from .const import LATEST_FINDINGS_FILENAME

_LOGGER = logging.getLogger(__name__)

MODEL = "gpt-6-astra"

_LEVEL_EMOJI = {"WARNING": "⚠️", "ERROR": "🛑", "CRITICAL": "🔴"}

_ANOMALY_HEADER_RE = re.compile(
    r"^#### \S+ (?P<level>WARNING|ERROR|CRITICAL) × (?P<count>\d+) — (?P<logger>.+)$"
)
_META_RE = re.compile(r"^- (?P<key>Signature|First seen|Last seen): (?P<value>.+)$")

SYSTEM_PROMPT = """\
You are Log Doctor's investigation stage, helping a Home Assistant user \
understand and resolve problems found in their Home Assistant log.

For each anomaly you are given the logger name, severity, how many times \
it occurred, and the raw matching log lines (including any traceback). \
Research it - search the web if it helps (Home Assistant docs, GitHub \
issues, the Community forum, release notes, etc.) - and give a concise, \
practical answer covering:

1. What the error means.
2. The most likely cause(s).
3. Concrete troubleshooting or resolution steps.

If you cannot determine anything useful about this specific error, say so \
plainly instead of guessing or padding the answer. Keep it tight - a short \
paragraph or a short bullet list, not an essay. You are only advising the \
user; never phrase suggestions as if you were about to take the action \
yourself.\
"""


@dataclass
class Anomaly:
    """One anomaly block parsed out of a Log Doctor markdown report."""

    level: str
    count: int
    logger: str
    signature: str
    first_seen: str
    last_seen: str
    log_text: str


@dataclass
class InvestigationResult:
    """What happened when a report was investigated."""

    investigated: int = 0
    skipped_over_cap: int = 0
    findings_file: str | None = None
    error: str | None = None


def parse_report(text: str) -> list[Anomaly]:
    """Split a Log Doctor markdown report into its per-anomaly blocks.

    Kept in sync by hand with companion/log_doctor_companion.py's parser of
    the same name - the two are separately deployed (this one ships inside
    the integration; that one is a standalone script) so they can't share
    a module, but they parse the same digest.py-produced format.
    """
    anomalies: list[Anomaly] = []
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        header = _ANOMALY_HEADER_RE.match(lines[i])
        if not header:
            i += 1
            continue

        meta = {"Signature": "", "First seen": "", "Last seen": ""}
        i += 1
        while i < len(lines) and lines[i].startswith("- "):
            match = _META_RE.match(lines[i])
            if match:
                meta[match.group("key")] = match.group("value").strip("`")
            i += 1

        while i < len(lines) and not lines[i].startswith("```"):
            i += 1

        log_lines: list[str] = []
        if i < len(lines) and lines[i].startswith("```"):
            i += 1
            while i < len(lines) and not lines[i].startswith("```"):
                log_lines.append(lines[i])
                i += 1
            i += 1  # skip the closing fence

        anomalies.append(
            Anomaly(
                level=header.group("level"),
                count=int(header.group("count")),
                logger=header.group("logger"),
                signature=meta["Signature"],
                first_seen=meta["First seen"],
                last_seen=meta["Last seen"],
                log_text="\n".join(log_lines).strip(),
            )
        )
    return anomalies


async def _async_research_anomaly(client: AsyncOpenAI, anomaly: Anomaly) -> str:
    """Ask the model to research one anomaly and return its findings as text."""
    user_prompt = (
        f"Logger: {anomaly.logger}\n"
        f"Severity: {anomaly.level}\n"
        f"Occurrences: {anomaly.count} (first seen {anomaly.first_seen}, "
        f"last seen {anomaly.last_seen})\n\n"
        f"Log lines:\n```\n{anomaly.log_text}\n```"
    )

    response = await client.responses.create(
        model=MODEL,
        instructions=SYSTEM_PROMPT,
        input=user_prompt,
        tools=[{"type": "web_search"}],
    )

    text = (response.output_text or "").strip()
    return text or "No information available"


def _build_findings_markdown(source_path: Path, findings: list[tuple[Anomaly, str]]) -> str:
    lines = [
        "# Log Doctor Investigation findings",
        "",
        f"_Researched from `{source_path}` using {MODEL}._",
    ]

    if not findings:
        lines.append("")
        lines.append("No anomalies found in the report - nothing to research.")
        return "\n".join(lines) + "\n"

    for anomaly, text in findings:
        emoji = _LEVEL_EMOJI.get(anomaly.level, "•")
        lines.append("")
        lines.append(f"## {emoji} {anomaly.level} × {anomaly.count} — {anomaly.logger}")
        lines.append(f"- Signature: `{anomaly.signature}`")
        lines.append(f"- First seen: {anomaly.first_seen}")
        lines.append(f"- Last seen: {anomaly.last_seen}")
        lines.append("")
        lines.append(text)

    return "\n".join(lines) + "\n"


def _write_findings_sync(
    report_path: Path, findings_markdown: str, retention_days: int
) -> str:
    findings_path = report_path.with_name(report_path.stem + ".findings.md")
    findings_path.write_text(findings_markdown, encoding="utf-8")

    latest_path = report_path.parent / LATEST_FINDINGS_FILENAME
    latest_path.write_text(findings_markdown, encoding="utf-8")

    if retention_days > 0:
        cutoff = datetime.now() - timedelta(days=retention_days)
        for existing in report_path.parent.glob("log_doctor_report_*.findings.md"):
            try:
                mtime = datetime.fromtimestamp(existing.stat().st_mtime)
            except OSError:
                continue
            if mtime < cutoff:
                try:
                    existing.unlink()
                except OSError:
                    _LOGGER.debug("Could not prune old findings file %s", existing)

    return str(findings_path)


async def async_investigate_report(
    hass: HomeAssistant,
    report_path: Path,
    openai_api_key: str,
    max_investigated: int,
    report_retention_days: int,
) -> InvestigationResult:
    """Research every anomaly in a just-written report with an OpenAI model.

    Runs as its own background task after a scan (see coordinator.py) so a
    slow investigation - one API call per anomaly - never delays the scan
    itself or the "Scan now" service call returning.
    """
    try:
        text = await hass.async_add_executor_job(report_path.read_text, "utf-8")
    except OSError as err:
        return InvestigationResult(error=f"Could not read report file: {err}")

    anomalies = parse_report(text)
    if not anomalies:
        return InvestigationResult()

    skipped_over_cap = max(0, len(anomalies) - max_investigated)
    anomalies = anomalies[:max_investigated]

    client = AsyncOpenAI(api_key=openai_api_key)

    results: list[tuple[Anomaly, str]] = []
    for anomaly in anomalies:
        try:
            findings = await _async_research_anomaly(client, anomaly)
        except openai.AuthenticationError as err:
            return InvestigationResult(
                error=f"Authentication with OpenAI failed: {err}"
            )
        except openai.APIStatusError as err:
            findings = f"No information available (OpenAI API error: {err.status_code} {err.message})"
        except openai.APIConnectionError as err:
            findings = f"No information available (network error: {err})"
        results.append((anomaly, findings))

    findings_markdown = _build_findings_markdown(report_path, results)
    try:
        findings_file = await hass.async_add_executor_job(
            _write_findings_sync, report_path, findings_markdown, report_retention_days
        )
    except OSError as err:
        return InvestigationResult(
            investigated=len(results), error=f"Could not write findings file: {err}"
        )

    return InvestigationResult(
        investigated=len(results),
        skipped_over_cap=skipped_over_cap,
        findings_file=findings_file,
    )
