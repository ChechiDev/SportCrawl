"""CLI header — printed once at the start of every sportcrawl command."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

import pyfiglet
from rich.console import Console
from rich.rule import Rule
from rich.text import Text


def _get_version() -> str:
    try:
        return version("sportcrawl")
    except PackageNotFoundError:
        return "dev"


def print_header(console: Console) -> None:
    v = _get_version()

    console.print(Rule(style="blue dim"))
    sport_lines = pyfiglet.figlet_format("SPORT", font="slant").splitlines()
    crawl_lines = pyfiglet.figlet_format("CRAWL", font="slant").splitlines()

    # Pad to same height
    height = max(len(sport_lines), len(crawl_lines))
    sport_lines += [""] * (height - len(sport_lines))
    crawl_lines += [""] * (height - len(crawl_lines))

    # Pad each sport line to consistent width
    sport_width = max(len(line) for line in sport_lines)

    for s, c in zip(sport_lines, crawl_lines):
        row = Text()
        row.append(s.ljust(sport_width), style="bold white")
        row.append(c, style="bold cyan")
        console.print(row)

    tagline = Text()
    tagline.append("  Sports data, scraped at scale.", style="dim white")
    tagline.append(f"  v{v}", style="dim cyan")
    console.print(tagline)
    hint = Text()
    hint.append(
        "  Ctrl+C to stop  ·  on restart, scraping resumes from where it",
        style="dim white",
    )
    hint.append(" left off", style="dim white")
    console.print(hint)
    console.print(Rule(style="blue dim"))
    console.print()
