"""Shared worker display helpers for scraper scripts.

Extracted from scrape_players.py and scrape_player_info.py (byte-identical bodies).
No logging side effects — safe to import from scripts that call logging.basicConfig.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable

from rich.console import Group
from rich.live import Live
from rich.markup import escape
from rich.padding import Padding
from rich.table import Table
from rich.text import Text


def build_worker_table(
    worker_labels: dict[int, str],
    worker_counts: dict[int, int],
    num_workers: int,
    already_done: int,
    total_jobs: int,
    notifications: list[str] | None = None,
) -> Group:
    global_done = already_done + sum(worker_counts.values())
    total_str = f"{global_done}/{total_jobs}" if total_jobs else str(global_done)
    table = Table.grid(padding=(0, 2))
    table.add_column(style="bold green")
    table.add_column()
    _COOLDOWN_PREFIX = "__cooldown__"
    for i in range(1, num_workers + 1):
        own = worker_counts.get(i, 0)
        label = worker_labels.get(i, "Starting crawl...")
        if label.startswith(_COOLDOWN_PREFIX):
            end = float(label[len(_COOLDOWN_PREFIX) :])
            remaining = max(0, int(end - time.monotonic()))
            label = f"[bold orange1]COOLDOWN[/] Resuming in {remaining}s"
        base = escape(f"[Crawl-{i}] [{own} | {total_str}] ")
        table.add_row("RUN", base + label)
    note_texts: list[Text] = (
        [Text(f"  {msg}", style="dim yellow") for msg in notifications[:3]]
        if notifications
        else []
    )
    return Group(Padding(table, pad=(0, 0, 0, 2)), *note_texts)


async def run_display_loop(
    num_workers: int,
    worker_labels: dict[int, str],
    worker_counts: dict[int, int],
    already_done: int,
    total_jobs: int,
    stop_event: asyncio.Event,
    live: Live,
    get_notifications: Callable[[], list[str]] | None = None,
) -> None:
    while not stop_event.is_set():
        notes = get_notifications() if get_notifications is not None else None
        table = build_worker_table(
            worker_labels,
            worker_counts,
            num_workers,
            already_done,
            total_jobs,
            notes,
        )
        live.update(table)
        await asyncio.sleep(0.5)
    notes = get_notifications() if get_notifications is not None else None
    table = build_worker_table(
        worker_labels,
        worker_counts,
        num_workers,
        already_done,
        total_jobs,
        notes,
    )
    live.update(table)
