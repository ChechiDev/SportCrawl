from rich.console import Console

from core.preflight.result import CheckResult


def render_check(result: CheckResult, console: Console) -> None:
    icon = "✅" if result.passed else ("⚠️" if not result.fatal else "❌")
    console.print(f"  {icon} {result.name}: {result.detail}")


def render_summary(results: list[CheckResult], console: Console) -> None:
    passed = sum(1 for r in results if r.passed)
    console.print(f"\n  {passed}/{len(results)} checks passed")
