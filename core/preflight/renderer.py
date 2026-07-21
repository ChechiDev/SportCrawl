from rich.console import Console

from core.preflight.result import CheckResult


def render_check(result: CheckResult, console: Console) -> None:
    if result.passed:
        icon = "[bold green]OK  [/bold green]"
    elif not result.fatal:
        icon = "[bold yellow]WARN[/bold yellow]"
    else:
        icon = "[bold red]FAIL[/bold red]"
    console.print(f"  {icon}  {result.name}: {result.detail}")


def render_summary(results: list[CheckResult], console: Console) -> None:
    passed = sum(1 for r in results if r.passed)
    console.print(f"\n  {passed}/{len(results)} checks passed")


def render_compact(results: list[CheckResult], console: Console) -> None:
    """Print only failed/warned checks. If all pass, print a single summary line."""
    failures = [r for r in results if not r.passed]
    if not failures:
        passed = len(results)
        console.print(f"  [bold green]OK[/bold green]  All {passed} checks passed")
        return
    for result in failures:
        icon = "[bold yellow]WARN[/bold yellow]" if not result.fatal else "[bold red]FAIL[/bold red]"
        console.print(f"  {icon}  {result.name}: {result.detail}")
