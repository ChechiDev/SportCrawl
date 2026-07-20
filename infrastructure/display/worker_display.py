"""Shared worker display helpers for scraper scripts.

Extracted from scrape_players.py and scrape_player_info.py (byte-identical bodies).
No logging side effects — safe to import from scripts that call logging.basicConfig.
"""

from __future__ import annotations

import asyncio

from rich.console import Group
from rich.live import Live
from rich.markup import escape
from rich.padding import Padding
from rich.table import Table


def build_worker_table(
    worker_labels: dict[int, str],
    worker_counts: dict[int, int],
    num_workers: int,
    already_done: int,
    total_jobs: int,
) -> Group:
    global_done = already_done + sum(worker_counts.values())
    total_str = f"{global_done}/{total_jobs}" if total_jobs else str(global_done)
    table = Table.grid(padding=(0, 2))
    table.add_column(style="bold green")
    table.add_column()
    for i in range(1, num_workers + 1):
        own = worker_counts.get(i, 0)
        label = worker_labels.get(i, "Starting crawl...")
        base = escape(f"[Crawl-{i}] [{own} | {total_str}] ")
        table.add_row("RUN", base + label)
    return Group(Padding(table, pad=(0, 0, 0, 2)))


async def run_display_loop(
    num_workers: int,
    worker_labels: dict[int, str],
    worker_counts: dict[int, int],
    already_done: int,
    total_jobs: int,
    stop_event: asyncio.Event,
    live: Live,
) -> None:
    while not stop_event.is_set():
        table = build_worker_table(
            worker_labels, worker_counts, num_workers, already_done, total_jobs
        )
        live.update(table)
        await asyncio.sleep(0.5)
    table = build_worker_table(
        worker_labels, worker_counts, num_workers, already_done, total_jobs
    )
    live.update(table)
