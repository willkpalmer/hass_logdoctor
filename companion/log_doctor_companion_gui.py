#!/usr/bin/env python3
"""Log Doctor Companion - GUI.

A simple desktop front end for log_doctor_companion.py: pick a Log Doctor
markdown report with a file dialog, research its anomalies with Claude, and
open the resulting findings file when it's done.

Usage:
    python log_doctor_companion_gui.py

Requires the `anthropic` package and an Anthropic API key: set
ANTHROPIC_API_KEY, or run `ant auth login` first.
"""
from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext, ttk

sys.path.insert(0, str(Path(__file__).resolve().parent))

try:
    import anthropic

    from log_doctor_companion import (
        Anomaly,
        build_findings_markdown,
        parse_report,
        research_anomaly,
    )
except ImportError as _import_err:
    _root = tk.Tk()
    _root.withdraw()
    messagebox.showerror(
        "Log Doctor Companion",
        f"Missing dependency: {_import_err}\n\n"
        "Run `pip install -r requirements.txt` in the companion/ folder, then try again.",
    )
    _root.destroy()
    sys.exit(1)


def _open_file(path: Path) -> None:
    """Open a file with whatever the OS considers its default viewer."""
    if sys.platform == "win32":
        os.startfile(path)  # noqa: S606 - local file this app just wrote
    elif sys.platform == "darwin":
        subprocess.run(["open", str(path)], check=False)
    else:
        subprocess.run(["xdg-open", str(path)], check=False)


class CompanionApp(tk.Tk):
    """Main window: pick a report, process it, then view the findings."""

    def __init__(self) -> None:
        super().__init__()
        self.title("Log Doctor Companion")
        self.geometry("760x520")
        self.minsize(600, 380)

        self._input_path: Path | None = None
        self._output_path: Path | None = None
        self._worker: threading.Thread | None = None
        self._events: queue.Queue = queue.Queue()

        self._build_widgets()
        self.after(100, self._poll_events)

    # -- layout -------------------------------------------------------

    def _build_widgets(self) -> None:
        pad = {"padx": 8, "pady": 6}

        form = ttk.Frame(self)
        form.pack(fill="x", **pad)
        form.columnconfigure(1, weight=1)

        ttk.Label(form, text="Input report:").grid(row=0, column=0, sticky="w")
        self.input_var = tk.StringVar()
        ttk.Entry(form, textvariable=self.input_var, state="readonly").grid(
            row=0, column=1, sticky="ew", padx=(6, 6)
        )
        self.input_button = ttk.Button(form, text="Browse...", command=self._choose_input)
        self.input_button.grid(row=0, column=2)

        ttk.Label(form, text="Output file:").grid(row=1, column=0, sticky="w", pady=(6, 0))
        self.output_var = tk.StringVar()
        ttk.Entry(form, textvariable=self.output_var, state="readonly").grid(
            row=1, column=1, sticky="ew", padx=(6, 6), pady=(6, 0)
        )
        self.output_button = ttk.Button(form, text="Browse...", command=self._choose_output)
        self.output_button.grid(row=1, column=2, pady=(6, 0))

        buttons = ttk.Frame(self)
        buttons.pack(fill="x", **pad)
        self.process_button = ttk.Button(buttons, text="Process", command=self._start_processing)
        self.process_button.pack(side="left")
        self.view_button = ttk.Button(
            buttons, text="View output", command=self._view_output, state="disabled"
        )
        self.view_button.pack(side="left", padx=(8, 0))

        self.progress = ttk.Progressbar(self, mode="determinate")
        self.progress.pack(fill="x", **pad)

        self.status_var = tk.StringVar(value="Pick a Log Doctor report to begin.")
        ttk.Label(self, textvariable=self.status_var).pack(fill="x", padx=8)

        self.log = scrolledtext.ScrolledText(self, state="disabled", wrap="word")
        self.log.pack(fill="both", expand=True, **pad)

    # -- file selection -------------------------------------------------

    def _choose_input(self) -> None:
        default_dir = Path("log_doctor_reports")
        start_dir = default_dir if default_dir.exists() else Path.cwd()
        chosen = filedialog.askopenfilename(
            title="Select a Log Doctor report",
            initialdir=str(start_dir),
            filetypes=[("Markdown files", "*.md"), ("All files", "*.*")],
        )
        if not chosen:
            return

        self._input_path = Path(chosen)
        self.input_var.set(str(self._input_path))

        self._output_path = self._input_path.with_name(self._input_path.stem + ".findings.md")
        self.output_var.set(str(self._output_path))

        self.view_button.config(state="disabled")
        self.status_var.set("Ready to process.")

    def _choose_output(self) -> None:
        initial_dir = str(self._output_path.parent) if self._output_path else str(Path.cwd())
        initial_file = self._output_path.name if self._output_path else "findings.md"
        chosen = filedialog.asksaveasfilename(
            title="Choose where to save findings",
            initialdir=initial_dir,
            initialfile=initial_file,
            defaultextension=".md",
            filetypes=[("Markdown files", "*.md"), ("All files", "*.*")],
        )
        if not chosen:
            return
        self._output_path = Path(chosen)
        self.output_var.set(str(self._output_path))

    # -- processing -------------------------------------------------------

    def _start_processing(self) -> None:
        if self._worker and self._worker.is_alive():
            return
        if not self._input_path or not self._input_path.exists():
            messagebox.showerror("Log Doctor Companion", "Choose a valid input report first.")
            return
        if not self._output_path:
            self._output_path = self._input_path.with_name(
                self._input_path.stem + ".findings.md"
            )
            self.output_var.set(str(self._output_path))

        try:
            text = self._input_path.read_text(encoding="utf-8")
        except OSError as err:
            messagebox.showerror("Log Doctor Companion", f"Could not read report: {err}")
            return

        anomalies = parse_report(text)
        if not anomalies:
            self._append_log("No anomalies found in this report - nothing to research.")
            self.status_var.set("No anomalies found.")
            return

        self._set_busy(True)
        self._append_log(f"Researching {len(anomalies)} anomalies from {self._input_path}...")
        self.progress.config(mode="determinate", maximum=len(anomalies), value=0)
        self.status_var.set(f"Researching {len(anomalies)} anomalies...")

        self._worker = threading.Thread(
            target=self._run_research,
            args=(anomalies, self._input_path, self._output_path),
            daemon=True,
        )
        self._worker.start()

    def _run_research(
        self, anomalies: list[Anomaly], input_path: Path, output_path: Path
    ) -> None:
        try:
            client = anthropic.Anthropic()
        except Exception as err:  # noqa: BLE001 - surface any client-construction failure
            self._events.put(("error", f"Could not create Anthropic client: {err}"))
            return

        results: list[tuple[Anomaly, str]] = []
        for i, anomaly in enumerate(anomalies, 1):
            self._events.put(
                ("log", f"[{i}/{len(anomalies)}] {anomaly.logger} "
                 f"({anomaly.level} x{anomaly.count})...")
            )
            try:
                findings = research_anomaly(client, anomaly)
            except anthropic.AuthenticationError as err:
                self._events.put((
                    "error",
                    f"Authentication failed: {err.message}\n"
                    "Set ANTHROPIC_API_KEY, or run `ant auth login`, then try again.",
                ))
                return
            except anthropic.APIStatusError as err:
                findings = (
                    f"No information available (Claude API error: {err.status_code} {err.message})"
                )
            except anthropic.APIConnectionError as err:
                findings = f"No information available (network error: {err})"
            results.append((anomaly, findings))
            self._events.put(("progress", i))

        try:
            output_path.write_text(
                build_findings_markdown(input_path, results), encoding="utf-8"
            )
        except OSError as err:
            self._events.put(("error", f"Could not write findings file: {err}"))
            return

        self._events.put(("done", output_path))

    # -- thread-safe UI updates -------------------------------------------

    def _poll_events(self) -> None:
        try:
            while True:
                event = self._events.get_nowait()
                kind = event[0]
                if kind == "log":
                    self._append_log(event[1])
                elif kind == "progress":
                    self.progress.config(value=event[1])
                elif kind == "error":
                    self._append_log(f"ERROR: {event[1]}")
                    self.status_var.set("Failed.")
                    self._set_busy(False)
                    messagebox.showerror("Log Doctor Companion", event[1])
                elif kind == "done":
                    output_path = event[1]
                    self._append_log(f"Findings written to {output_path}")
                    self.status_var.set(f"Done - {output_path.name}")
                    self._set_busy(False)
                    self.view_button.config(state="normal")
        except queue.Empty:
            pass
        self.after(100, self._poll_events)

    def _set_busy(self, busy: bool) -> None:
        state = "disabled" if busy else "normal"
        self.process_button.config(state=state)
        self.input_button.config(state=state)
        self.output_button.config(state=state)

    def _append_log(self, message: str) -> None:
        self.log.config(state="normal")
        self.log.insert("end", message + "\n")
        self.log.see("end")
        self.log.config(state="disabled")

    def _view_output(self) -> None:
        if self._output_path and self._output_path.exists():
            try:
                _open_file(self._output_path)
            except OSError as err:
                messagebox.showerror("Log Doctor Companion", f"Could not open file: {err}")


def main() -> None:
    app = CompanionApp()
    app.mainloop()


if __name__ == "__main__":
    main()
