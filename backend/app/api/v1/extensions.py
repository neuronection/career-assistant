"""Extension surfaces (plan 32 Phase 4 / ADR-0040 clause 16): the
career surface host's thin router. Installed mini-app extensions declare
``ui:page`` / ``ui:panel`` declarative schemas; this domain serves their
RENDER VIEWS (nodes + resolved labels + rows assembled from the declared
T0 data) to the frontend, which renders through the family
SurfaceRenderer — never extension markup (D17). Kill-switch law: only
ENABLED installs surface here (disabling hides the route, D25)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.user_model import User
from app.services.deps import get_current_user

router = APIRouter(prefix="/extensions", tags=["extensions"])


def _requested_locales(request: Request) -> list[str]:
    """The Accept-Language preference list (quality-ordered) — the host's
    locale resolution input; the view clamps it to the manifest's declared
    locales (the family string rule)."""
    header = request.headers.get("accept-language") or ""
    parts: list[tuple[float, str]] = []
    for token in header.split(","):
        token = token.strip()
        if not token:
            continue
        params = token.split(";")
        tag = params[0].strip()
        if not tag:
            continue
        quality = 1.0
        for param in params[1:]:
            if param.strip().startswith("q="):
                try:
                    quality = float(param.strip().removeprefix("q="))
                except ValueError:
                    quality = 0.0
        parts.append((quality, tag))
    ordered = [tag for _, tag in sorted(parts, key=lambda pair: -pair[0])]
    return ordered or ["en"]


@router.get("/surfaces")
async def list_extension_surfaces(
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """One registry view (D25): installed + enabled mini-apps with their
    surface capability view (honored page/panel, recorded window degrades)
    (origin chips) — consumed by the nav's Extensions section."""
    from app.extensions import surface_host

    return await surface_host.list_surface_cards(db, locales=_requested_locales(request))


@router.get("/surfaces/{extension_id}")
async def extension_surface(
    extension_id: str,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """One mini-app's render view for the routed page surface. A disabled
    or missing install is 404 — the page route is the kill switch's
    data-driven boundary."""
    from app.extensions import surface_host

    try:
        return await surface_host.surface_page_view(
            db, extension_id, locales=_requested_locales(request)
        )
    except LookupError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "surface not available") from None


@router.get("/surfaces/{extension_id}/export")
async def export_extension_surface(
    extension_id: str,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """The ``run:export`` typed action's funnel for surface pages (the run
    capability honored as the typed-action funnel in the Phase-4 profile):
    the same bounded view the page renders, as a JSON deck."""
    from app.extensions import surface_host

    try:
        view = await surface_host.surface_page_view(
            db, extension_id, locales=_requested_locales(request)
        )
    except LookupError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "surface not available") from None
    surface = view.get("surface") or {}
    return {
        "extensionId": extension_id,
        "version": view.get("version"),
        "source": "career-assistant/extensions",
        "rows": surface.get("rows", []),
        "values": surface.get("values", {}),
    }
