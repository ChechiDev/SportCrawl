"""CLI entry point for sportcrawl.

Commands:
- work-server: start the aiohttp work server with a shared JobLoop event loop.
"""

from __future__ import annotations

import asyncio

import typer

from config.settings import Settings
from infrastructure.work_server.runtime import serve

app = typer.Typer(name="sportcrawl", help="Sportcrawl CLI")


@app.command("work-server")
def work_server() -> None:
    """Start the aiohttp work server and JobLoop in a single process."""
    settings = Settings()  # type: ignore[call-arg]
    asyncio.run(serve(settings))


def main() -> None:
    """Run the CLI."""
    app()
