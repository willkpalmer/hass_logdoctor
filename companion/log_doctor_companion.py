#!/usr/bin/env python3
"""Log Doctor Companion.

Run this separately, whenever you want, against a report the Log Doctor
Home Assistant integration wrote to `log_doctor_reports/`. It reads that
markdown report, asks an OpenAI model to research each listed anomaly
(with web search enabled, so it can check the Home Assistant docs, GitHub
issues, and the Community forum), and writes a findings file alongside the
report with a plain-English explanation and troubleshooting suggestions
for each one.

Log Doctor itself only lists raw log data - it never summarizes or
diagnoses. All of that happens here, on demand.

Usage:
    python log_doctor_companion.py [path/to/report.md] [-o output.md]

With no path given, you'll be prompted for one (defaulting to
`log_doctor_reports/latest.md` if it exists).

Requires the `openai` package and an OpenAI API key: set OPENAI_API_KEY.
"""
from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

import openai
from openai import OpenAI

MODEL = "gpt-6-astra"
DEFAULT_REPORT_DIR = "log_doctor_reports"
DEFAULT_REPORT_NAME = "latest.md"

_LEVEL_EMOJI = {"WARNING": "⚠️", "ERROR": "🛑", "CRITICAL": "🔴"}

_ANOMALY_HEADER_RE = re.compile(
    r"^#### \S+ (?P<level>WARNING|ERROR|CRITICAL) × (?P<count>\d+) — (?P<logger>.+)$"
)
_META_RE = re.compile(r"^- (?P<key>Signature|First seen|Last seen): (?P<value>.+)$")

SYSTEM_PROMPT = """\
You are Log Doctor's companion, helping a Home Assistant user understand \
and resolve problems found in their Home Assistant log.

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


def parse_report(text: str) -> list[Anomaly]:
    """Split a Log Doctor markdown report into its per-anomaly blocks."""
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


def default_report_path() -> Path:
    candidate = Path(DEFAULT_REPORT_DIR) / DEFAULT_REPORT_NAME
    if candidate.exists():
        return candidate
    return Path(DEFAULT_REPORT_NAME)


def resolve_report_path(cli_arg: str | None) -> Path:
    if cli_arg:
        return Path(cli_arg)
    default = default_report_path()
    entered = input(f"Path to Log Doctor report [{default}]: ").strip()
    return Path(entered) if entered else default


def research_anomaly(client: OpenAI, anomaly: Anomaly) -> str:
    """Ask the model to research one anomaly and return its findings as text."""
    user_prompt = (
        f"Logger: {anomaly.logger}\n"
        f"Severity: {anomaly.level}\n"
        f"Occurrences: {anomaly.count} (first seen {anomaly.first_seen}, "
        f"last seen {anomaly.last_seen})\n\n"
        f"Log lines:\n```\n{anomaly.log_text}\n```"
    )

    response = client.responses.create(
        model=MODEL,
        instructions=SYSTEM_PROMPT,
        input=user_prompt,
        tools=[{"type": "web_search"}],
    )

    text = (response.output_text or "").strip()
    return text or "No information available"


def build_findings_markdown(source_path: Path, findings: list[tuple[Anomaly, str]]) -> str:
    lines = [
        "# Log Doctor Companion findings",
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


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Research a Log Doctor report's anomalies with an OpenAI model."
    )
    parser.add_argument(
        "report",
        nargs="?",
        help="Path to a Log Doctor markdown report. If omitted, you'll be "
        "prompted (default: log_doctor_reports/latest.md).",
    )
    parser.add_argument(
        "-o",
        "--output",
        help="Where to write the findings markdown "
        "(default: <report>.findings.md next to the report).",
    )
    args = parser.parse_args()

    report_path = resolve_report_path(args.report)
    if not report_path.exists():
        print(f"Report not found: {report_path}", file=sys.stderr)
        sys.exit(1)

    anomalies = parse_report(report_path.read_text(encoding="utf-8"))
    if not anomalies:
        print("No anomalies found in this report - nothing to research.")
        return

    try:
        client = OpenAI()
    except openai.OpenAIError as err:
        print(f"\nCould not authenticate with OpenAI: {err}\nSet OPENAI_API_KEY, then try again.", file=sys.stderr)
        sys.exit(1)

    print(f"Researching {len(anomalies)} anomal{'y' if len(anomalies) == 1 else 'ies'} "
          f"from {report_path}...")
    results: list[tuple[Anomaly, str]] = []
    for i, anomaly in enumerate(anomalies, 1):
        print(f"  [{i}/{len(anomalies)}] {anomaly.logger} ({anomaly.level} x{anomaly.count})...")
        try:
            findings = research_anomaly(client, anomaly)
        except openai.AuthenticationError as err:
            print(
                f"\nAuthentication failed: {err}\nSet OPENAI_API_KEY, then try again.",
                file=sys.stderr,
            )
            sys.exit(1)
        except openai.APIStatusError as err:
            findings = f"No information available (OpenAI API error: {err.status_code} {err.message})"
        except openai.APIConnectionError as err:
            findings = f"No information available (network error: {err})"
        results.append((anomaly, findings))

    output_path = (
        Path(args.output)
        if args.output
        else report_path.with_name(report_path.stem + ".findings.md")
    )
    output_path.write_text(build_findings_markdown(report_path, results), encoding="utf-8")
    print(f"Findings written to {output_path}")


if __name__ == "__main__":
    main()
