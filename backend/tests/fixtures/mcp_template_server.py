"""The reference career-assistant posting fetcher (T3 script tier).

This server speaks the family fetch contract — one tool:

    fetch_postings(config: dict, state: dict) -> {
        "items": [RawPosting, ...],      # 0..300 rows
        "next_state": {"etag": "..."}    # opaque cursor, round-tripped
    }

Career-assistant calls it as an external MCP server (stdio subprocess
or http endpoint) through its ``mcp`` connector. Everything the tool
returns is UNTRUSTED: the app validates every row against its
RawPosting schema (required external_id/title, http(s) urls, char
caps, a 300-item cap) before persisting anything — malformed rows are
dropped as typed errors, so keep rows honest and small.

The etag pattern below is the whole incremental story: digest the
stable identity of your rows, return it as next_state, and when the
caller hands the same cursor back, return no rows.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta

from fastmcp import FastMCP

mcp = FastMCP("reference-posting-fetcher")


def _rows(board: str) -> list[dict]:
    """Your real fetcher hits an API or scrapes here — the script's own
    network calls are its own business (T3 runs outside the app's
    perimeter; see docs/authoring.md)."""
    return [
        {
            "external_id": f"{board}-1",
            "title": "Backend Engineer (Python)",
            "org": "Reference Systems",
            "url": f"https://jobs.example.com/{board}/1",
            "posted_at": (datetime.now(UTC) - timedelta(days=2)).isoformat(),
            "seniority": "mid",
            "employment_type": "full_time",
            "skills_raw": ["python", "sql", "postgresql"],
            "raw": {"description": "Build ingestion connectors and data pipelines."},
        },
        {
            "external_id": f"{board}-2",
            "title": "Data Platform Engineer",
            "org": "Reference Systems",
            "url": f"https://jobs.example.com/{board}/2",
            "posted_at": (datetime.now(UTC) - timedelta(days=4)).isoformat(),
            "seniority": "senior",
            "skills_raw": ["python", "kubernetes", "docker"],
            "raw": {"description": "Own the platform that ships job data."},
        },
        {
            "external_id": f"{board}-3",
            "title": "QA Automation Engineer",
            "org": "Reference Systems",
            "url": f"https://jobs.example.com/{board}/3",
            "posted_at": (datetime.now(UTC) - timedelta(days=1)).isoformat(),
            "employment_type": "contract",
            "skills_raw": ["python", "testing"],
        },
    ]


@mcp.tool
def fetch_postings(config: dict, state: dict) -> dict:
    """Return the board's RawPosting rows plus an etag cursor.

    config: the per-source config declared in manifest.json
    state:  the last next_state this tool returned (empty on first run)
    """
    board = str(config.get("board") or "default")
    rows = _rows(board)
    digest = json.dumps(
        [[row["external_id"], row["title"], row["url"]] for row in rows], sort_keys=True
    )
    etag = '"' + hashlib.sha256(digest.encode()).hexdigest()[:16] + '"'
    if state.get("etag") == etag:
        return {"items": [], "next_state": {"etag": etag}}
    return {"items": rows, "next_state": {"etag": etag}}


if __name__ == "__main__":
    mcp.run()
