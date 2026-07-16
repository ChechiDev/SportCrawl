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
    from rich.rule import Rule
    passed = sum(1 for r in results if r.passed)
    console.print(f"\n  {passed}/{len(results)} checks passed")
    console.print(Rule())
