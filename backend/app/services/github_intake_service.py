"""GitHub intake (plan 122 Phase 3): public repositories → project and
achievement DRAFTS.

Review-first by construction: every row lands with ``status='draft'`` and
``source='import'``; the existing draft surfaces in the profile are where a
student reviews and activates them. Nothing is ever written as ``active``.
The optional instance GitHub token (Settings → Tools → Connectors) raises
the API rate limit; public repositories need no token.
"""

from __future__ import annotations

import re
from datetime import datetime
from urllib.parse import quote

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ValidationError
from app.models.experience_model import ExperienceAchievement, ExperienceItem
from app.models.settings_model import AppSetting

GITHUB_API = "https://api.github.com"
GITHUB_DOMAINS = frozenset({"api.github.com"})
LOGIN_PATTERN = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?$")
MAX_REPOS = 30


async def instance_github_token(db: AsyncSession) -> str:
    """The sealed instance token set in Settings → Tools → Connectors."""
    from app.core.encryption import decrypt_secret

    row = (
        (await db.execute(select(AppSetting).where(AppSetting.key == "web.github_token")))
        .scalars()
        .first()
    )
    sealed = (row.value or {}).get("token") if row is not None else None
    return (decrypt_secret(sealed) or "") if isinstance(sealed, str) else ""


def validate_login(login: str) -> str:
    token = str(login or "").strip()
    if not LOGIN_PATTERN.fullmatch(token):
        raise ValidationError("a GitHub login is 1-39 letters, digits or hyphens")
    return token


def _normalize_repo(row: dict) -> dict:
    topics = row.get("topics") if isinstance(row.get("topics"), list) else []
    return {
        "name": str(row.get("name") or "")[:200],
        "full_name": str(row.get("full_name") or "")[:200],
        "description": str(row.get("description") or "")[:1000],
        "html_url": str(row.get("html_url") or "")[:1000],
        "homepage": str(row.get("homepage") or "")[:1000],
        "language": str(row.get("language") or "")[:60],
        "topics": [str(topic)[:60] for topic in topics][:12],
        "stars": int(row.get("stargazers_count") or 0),
        "forks": int(row.get("forks_count") or 0),
        "created_at": row.get("created_at"),
        "pushed_at": row.get("pushed_at"),
        "fork": bool(row.get("fork")),
    }


async def fetch_repos(
    login: str, *, token: str = "", transport=None, limit: int = MAX_REPOS
) -> list[dict]:
    """Public non-fork repositories, most-starred first, over the guard."""
    from app.extensions.runtime.http import build_transport

    user = validate_login(login)
    guarded = transport or build_transport(domains=GITHUB_DOMAINS)
    url = f"{GITHUB_API}/users/{quote(user)}/repos?sort=updated&per_page={limit}&type=owner"
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    response = await guarded(url, headers)
    if response.status == 404:
        raise ValidationError(f"GitHub user '{user}' not found")
    if response.status in (403, 429):
        raise ValidationError(
            "GitHub rate limit reached — add a token in Settings → Tools → Connectors"
        )
    if response.status != 200:
        raise ValidationError(f"GitHub returned status {response.status}")
    import json

    try:
        rows = json.loads(response.body)
    except ValueError as exc:
        raise ValidationError("GitHub returned a non-JSON body") from exc
    if not isinstance(rows, list):
        raise ValidationError("GitHub returned an unexpected payload")
    repos = [_normalize_repo(row) for row in rows if isinstance(row, dict)]
    repos = [repo for repo in repos if not repo["fork"] and repo["name"]]
    repos.sort(key=lambda repo: (repo["stars"], repo["pushed_at"] or ""), reverse=True)
    return repos[:limit]


async def preview(db: AsyncSession, login: str, *, transport=None) -> dict:
    """Draft candidates for review — no writes."""
    token = await instance_github_token(db)
    repos = await fetch_repos(login, token=token, transport=transport)
    return {
        "login": validate_login(login),
        "repos": [{"index": index, **repo} for index, repo in enumerate(repos)],
    }


def _existing_urls(items: list[ExperienceItem]) -> set[str]:
    urls: set[str] = set()
    for item in items:
        for link in item.links or []:
            if isinstance(link, dict) and link.get("url"):
                urls.add(str(link["url"]))
    return urls


def _repo_description(repo: dict) -> str:
    parts = [repo["description"]] if repo["description"] else []
    if repo["language"]:
        parts.append(f"Primary language: {repo['language']}.")
    if repo["topics"]:
        parts.append("Topics: " + ", ".join(repo["topics"]) + ".")
    return " ".join(parts)[:4000]


async def apply(
    db: AsyncSession, user_id, login: str, selections: list[int], *, transport=None
) -> dict:
    """Create DRAFT projects (and achievements) for the selected repos."""
    token = await instance_github_token(db)
    repos = await fetch_repos(login, token=token, transport=transport)
    selected = [repos[index] for index in selections if 0 <= index < len(repos)]
    if not selected:
        raise ValidationError("no repositories selected")
    existing = list(
        (
            await db.execute(
                select(ExperienceItem).where(
                    ExperienceItem.user_id == user_id,
                    ExperienceItem.kind == "project",
                )
            )
        )
        .scalars()
        .all()
    )
    known = _existing_urls(existing)
    created: list[str] = []
    skipped = 0
    for repo in selected:
        if repo["html_url"] in known:
            skipped += 1
            continue
        start = None
        if repo["created_at"]:
            try:
                start = datetime.fromisoformat(
                    str(repo["created_at"]).replace("Z", "+00:00")
                ).date()
            except ValueError:
                start = None
        item = ExperienceItem(
            user_id=user_id,
            kind="project",
            title=repo["name"][:160],
            org_name="GitHub",
            start=start,
            description=_repo_description(repo),
            links=[
                {"label": "GitHub", "url": repo["html_url"], "kind": "github"},
            ],
            source="import",
            status="draft",
        )
        db.add(item)
        await db.flush()
        if repo["stars"] or repo["forks"]:
            db.add(
                ExperienceAchievement(
                    experience_id=item.id,
                    text=f"{repo['stars']} GitHub stars · {repo['forks']} forks"[:500],
                    metric={
                        "kind": "scale",
                        "value": repo["stars"],
                        "unit": "stars",
                    },
                )
            )
        known.add(repo["html_url"])
        created.append(str(item.id))
    await db.commit()
    return {"created": len(created), "skipped": skipped, "draft_ids": created}


__all__ = [
    "GITHUB_DOMAINS",
    "apply",
    "fetch_repos",
    "instance_github_token",
    "preview",
    "validate_login",
]
