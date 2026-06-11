#!/usr/bin/env python3
"""
Baseline Framework — Live Test Runner
======================================
Runs the full test suite against the live Docker stack and produces
a rich real-time report with per-test timing and a final summary.

Usage:
    # From within the test container (docker compose run):
    python run_tests.py

    # With an authenticated token for L2+ tests:
    TEST_API_TOKEN=your_token python run_tests.py

    # Targeting a remote/local stack:
    GATEWAY_URL=http://localhost:8000 python run_tests.py
"""
import sys
import os

# Guard: this script must run inside the Docker test container.
# Outside Docker, pytest and the other dependencies are not installed.
if not os.path.exists("/.dockerenv"):
    print()
    print("  \033[1;31mError:\033[0m run_tests.py must be executed inside the Docker test container.")
    print()
    print("  Use the test runner script instead:")
    print()
    print("    \033[1;36m./test.sh\033[0m")
    print()
    print("  Or run the container directly:")
    print()
    print("    \033[1;36mdocker compose -f docker-compose.yml -f docker-compose.test.yml run --rm test-runner\033[0m")
    print()
    sys.exit(1)

import time

import pytest
from rich.console import Console
from rich.rule import Rule
from rich import box
from rich.table import Table
from rich.text import Text

console = Console()


class RichReporter:
    """
    Pytest plugin that intercepts test results and renders them live
    with status, test name, and response time.
    """

    STATUS_STYLES = {
        "passed":  ("green",  "✓ PASS"),
        "failed":  ("red",    "✗ FAIL"),
        "skipped": ("yellow", "○ SKIP"),
        "error":   ("red",    "! ERROR"),
    }

    def __init__(self):
        self.results: list[dict] = []
        self.current_suite: str = ""
        self._suite_start: float = 0

    # ── Hooks ────────────────────────────────────────────────────────────────

    def pytest_runtest_logreport(self, report):
        if report.when != "call" and report.when != "setup":
            return
        if report.when == "setup" and report.skipped:
            self._emit(report, "skipped")
            return
        if report.when != "call":
            return
        self._emit(report, report.outcome)

    def _emit(self, report, outcome: str):
        # Extract suite from node id (filename without .py)
        parts = report.nodeid.split("::")
        suite_raw = parts[0].replace("suites/", "").replace(".py", "")
        # Human-readable: "test_01_health" → "01 Health"
        suite_label = suite_raw.replace("test_", "").replace("_", " ").title()

        if suite_label != self.current_suite:
            self.current_suite = suite_label
            console.print()
            console.print(Rule(f"[bold cyan]{suite_label}[/bold cyan]", style="cyan"))

        test_name = "::".join(parts[1:]).replace("test_", "").replace("_", " ")
        duration_ms = getattr(report, "duration", 0) * 1000

        color, label = self.STATUS_STYLES.get(outcome, ("white", "? UNKNOWN"))

        status_text = Text(f" {label} ", style=f"bold {color}")
        name_text   = Text(f" {test_name:<65}", style="white")
        ms_color    = "green" if duration_ms < 200 else ("yellow" if duration_ms < 1000 else "red")
        ms_text     = Text(f" {duration_ms:>7.1f} ms", style=ms_color)

        console.print(status_text + name_text + ms_text, highlight=False)

        if outcome == "failed":
            # Show short failure reason
            if report.longreprtext:
                lines = report.longreprtext.strip().splitlines()
                # Show the last meaningful line (usually the AssertionError)
                for line in reversed(lines):
                    if "AssertionError" in line or "assert" in line.lower():
                        console.print(f"    [dim]{line.strip()[:120]}[/dim]")
                        break

        self.results.append({
            "suite": suite_label,
            "name": test_name,
            "outcome": outcome,
            "duration_ms": duration_ms,
            "failed": outcome in ("failed", "error"),
        })

    # ── Summary ───────────────────────────────────────────────────────────────

    def print_summary(self) -> bool:
        console.print()
        console.print(Rule("[bold white]Test Summary[/bold white]", style="white"))

        # Group by suite
        suites: dict[str, list] = {}
        for r in self.results:
            suites.setdefault(r["suite"], []).append(r)

        table = Table(box=box.ROUNDED, show_header=True, header_style="bold white",
                      expand=False, min_width=80)
        table.add_column("Suite",   style="cyan",   min_width=35)
        table.add_column("Pass",    justify="right", style="green",  min_width=6)
        table.add_column("Fail",    justify="right", style="red",    min_width=6)
        table.add_column("Skip",    justify="right", style="yellow", min_width=6)
        table.add_column("Avg ms",  justify="right",                 min_width=9)
        table.add_column("Max ms",  justify="right",                 min_width=9)
        table.add_column("Total",   justify="right",                 min_width=7)

        total_pass = total_fail = total_skip = 0

        for suite_name, items in suites.items():
            passed  = [x for x in items if x["outcome"] == "passed"]
            failed  = [x for x in items if x["outcome"] in ("failed", "error")]
            skipped = [x for x in items if x["outcome"] == "skipped"]
            total_pass  += len(passed)
            total_fail  += len(failed)
            total_skip  += len(skipped)

            times = [x["duration_ms"] for x in items if x["duration_ms"] > 0]
            avg_ms = sum(times) / len(times) if times else 0
            max_ms = max(times) if times else 0

            fail_str = Text(str(len(failed)), style="bold red") if failed else Text("-", style="dim")
            skip_str = Text(str(len(skipped)), style="yellow") if skipped else Text("-", style="dim")

            table.add_row(
                suite_name,
                str(len(passed)),
                fail_str,
                skip_str,
                f"{avg_ms:.0f}",
                f"{max_ms:.0f}",
                str(len(items)),
            )

        console.print(table)
        console.print()

        total = total_pass + total_fail + total_skip
        pct = (total_pass / total * 100) if total else 0
        result_color = "green" if total_fail == 0 else "red"

        console.print(
            f"  [bold {result_color}]{total_pass}/{total} passed ({pct:.0f}%)[/bold {result_color}]"
            f"   [red]{total_fail} failed[/red]"
            f"   [yellow]{total_skip} skipped[/yellow]"
        )

        # Failures detail
        failures = [r for r in self.results if r["failed"]]
        if failures:
            console.print()
            console.print(Rule("[bold red]Failed Tests[/bold red]", style="red"))
            for r in failures:
                console.print(f"  [red]✗[/red]  {r['suite']} › {r['name']}")

        console.print()
        return total_fail == 0


def _check_setup_complete(gateway_url: str) -> bool:
    """Return True if the setup wizard has been completed on the target stack."""
    try:
        import httpx as _httpx
        r = _httpx.get(
            f"{gateway_url}/api/v1/setup/state",
            timeout=10,
            follow_redirects=False,
        )
        if r.status_code == 200:
            return bool(r.json().get("setup_complete", False))
    except Exception:
        pass
    return False


def main():
    console.print()
    console.print(Rule(
        "[bold white]Baseline Framework — Live Test Suite[/bold white]",
        style="bright_blue"
    ))
    console.print()

    gateway_url = os.environ.get("GATEWAY_URL", "http://gateway")
    console.print(f"  Gateway:  [cyan]{gateway_url}[/cyan]")
    console.print(f"  Backend:  [cyan]{os.environ.get('BACKEND_URL', 'http://backend:8000')}[/cyan]")
    token = os.environ.get("TEST_API_TOKEN", "")
    if token:
        console.print(f"  Token:    [green]provided (authenticated tests enabled)[/green]")
    else:
        console.print(f"  Token:    [yellow]not set — L2+ authenticated tests will be skipped[/yellow]")
        console.print(f"  [dim]Set TEST_API_TOKEN env var to enable authenticated tests[/dim]")

    # ── Setup Wizard Pre-flight Check ──────────────────────────────────────────
    console.print()
    setup_ok = _check_setup_complete(gateway_url)
    if setup_ok:
        console.print(f"  Setup:    [green]✓ wizard complete — all tests will run[/green]")
    else:
        console.print(f"  Setup:    [bold red]✗ wizard NOT complete[/bold red]")
        console.print(f"  [yellow]All tests will be skipped until the setup wizard is run.[/yellow]")
        console.print(f"  [dim]Open the web UI and complete setup at /setup, then re-run.[/dim]")

    # ── Suite filter (TEST_SUITES=01,03,07 runs only those suites) ────────────
    suites_env = os.environ.get("TEST_SUITES", "").strip()
    if suites_env:
        import glob as _glob
        nums = [s.strip().zfill(2) for s in suites_env.split(",") if s.strip()]
        pytest_targets = []
        for num in nums:
            pytest_targets.extend(sorted(_glob.glob(f"suites/test_{num}_*.py")))
        if not pytest_targets:
            console.print(f"  [bold red]No suites matched TEST_SUITES={suites_env!r}[/bold red]")
            sys.exit(1)
        console.print(f"  Suites:   [cyan]{', '.join(nums)}[/cyan]  ({len(pytest_targets)} file(s))")
    else:
        pytest_targets = ["suites/"]
        console.print(f"  Suites:   [cyan]all[/cyan]")

    console.print()

    start = time.monotonic()
    reporter = RichReporter()

    exit_code = pytest.main(
        [
            *pytest_targets,
            "-v",
            "--tb=no",          # We handle failure output ourselves
            "--no-header",
            "-q",
            "--timeout=30",
        ],
        plugins=[reporter],
    )

    elapsed = time.monotonic() - start
    passed = reporter.print_summary()

    console.print(f"  Total elapsed: [dim]{elapsed:.2f}s[/dim]")
    console.print()

    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()
