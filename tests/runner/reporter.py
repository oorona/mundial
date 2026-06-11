"""
Real-time rich test reporter for the Baseline framework test suite.

Shows each test result as it runs with:
  - Test name
  - PASS / FAIL / SKIP / ERROR status
  - Response time (where applicable)
  - Final summary table with per-suite stats
"""
import time
from typing import Optional
from rich.console import Console
from rich.table import Table
from rich.text import Text
from rich.rule import Rule
from rich import box

console = Console()

# ─── Result store ─────────────────────────────────────────────────────────────

class TestResult:
    def __init__(self, name: str, suite: str, status: str,
                 duration_ms: float, message: str = ""):
        self.name = name
        self.suite = suite
        self.status = status          # PASS | FAIL | SKIP | ERROR
        self.duration_ms = duration_ms
        self.message = message

results: list[TestResult] = []
suite_start_times: dict[str, float] = {}

# ─── Styling helpers ──────────────────────────────────────────────────────────

STATUS_STYLES = {
    "PASS":  ("green",   "✓"),
    "FAIL":  ("red",     "✗"),
    "SKIP":  ("yellow",  "○"),
    "ERROR": ("red bold","!"),
}

def _status_text(status: str) -> Text:
    color, icon = STATUS_STYLES.get(status, ("white", "?"))
    return Text(f"{icon} {status}", style=color)

def _ms(ms: float) -> Text:
    if ms < 100:
        color = "green"
    elif ms < 500:
        color = "yellow"
    else:
        color = "red"
    return Text(f"{ms:.1f} ms", style=color)

# ─── Public API ───────────────────────────────────────────────────────────────

def suite_start(suite_name: str):
    suite_start_times[suite_name] = time.time()
    console.print(Rule(f"[bold cyan]{suite_name}[/bold cyan]", style="cyan"))

def record(name: str, suite: str, status: str,
           duration_ms: float, message: str = ""):
    result = TestResult(name=name, suite=suite, status=status,
                        duration_ms=duration_ms, message=message)
    results.append(result)

    status_text = _status_text(status)
    ms_text = _ms(duration_ms)

    console.print(
        f"  {status_text}  {name:<60}  {ms_text}",
        highlight=False,
    )
    if status in ("FAIL", "ERROR") and message:
        console.print(f"       [dim]{message}[/dim]")

def print_summary():
    console.print()
    console.print(Rule("[bold]Test Summary[/bold]", style="white"))

    # Per-suite breakdown
    suites: dict[str, list[TestResult]] = {}
    for r in results:
        suites.setdefault(r.suite, []).append(r)

    summary_table = Table(
        box=box.ROUNDED,
        show_header=True,
        header_style="bold white",
        expand=True,
    )
    summary_table.add_column("Suite", style="cyan", ratio=3)
    summary_table.add_column("Pass", justify="right", style="green", ratio=1)
    summary_table.add_column("Fail", justify="right", style="red", ratio=1)
    summary_table.add_column("Skip", justify="right", style="yellow", ratio=1)
    summary_table.add_column("Avg ms", justify="right", ratio=1)
    summary_table.add_column("Max ms", justify="right", ratio=1)

    total_pass = total_fail = total_skip = 0

    for suite_name, suite_results in suites.items():
        passed  = [r for r in suite_results if r.status == "PASS"]
        failed  = [r for r in suite_results if r.status in ("FAIL", "ERROR")]
        skipped = [r for r in suite_results if r.status == "SKIP"]

        total_pass += len(passed)
        total_fail += len(failed)
        total_skip += len(skipped)

        times = [r.duration_ms for r in suite_results if r.duration_ms > 0]
        avg_ms = sum(times) / len(times) if times else 0
        max_ms = max(times) if times else 0

        summary_table.add_row(
            suite_name,
            str(len(passed)),
            str(len(failed)) if failed else "-",
            str(len(skipped)) if skipped else "-",
            f"{avg_ms:.1f}",
            f"{max_ms:.1f}",
        )

    console.print(summary_table)

    # Overall totals
    total = total_pass + total_fail + total_skip
    pct = (total_pass / total * 100) if total else 0
    color = "green" if total_fail == 0 else "red"

    console.print()
    console.print(
        f"  [bold {color}]{total_pass}/{total} passed[/bold {color}]  "
        f"({pct:.1f}%)   "
        f"[red]{total_fail} failed[/red]   "
        f"[yellow]{total_skip} skipped[/yellow]"
    )
    console.print()

    # Failures detail
    failures = [r for r in results if r.status in ("FAIL", "ERROR")]
    if failures:
        console.print(Rule("[bold red]Failures[/bold red]", style="red"))
        for r in failures:
            console.print(f"  [red]✗[/red] [bold]{r.suite}[/bold] › {r.name}")
            if r.message:
                console.print(f"    [dim]{r.message}[/dim]")
        console.print()

    return total_fail == 0
