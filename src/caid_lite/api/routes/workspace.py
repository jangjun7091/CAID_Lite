"""GET /api/parts/{id}/step|stl — serve geometry files for download."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from ..deps import get_manager
from ...session.manager import SessionManager

router = APIRouter(tags=["workspace"])

_MEDIA_TYPES = {
    "step": "application/step",
    "stl": "model/stl",
}


def _serve_export(part_id: str, fmt: str, manager: SessionManager) -> FileResponse:
    part = manager.get_part(part_id)
    if part is None:
        raise HTTPException(status_code=404, detail=f"Part '{part_id}' not found.")
    if part.status != "ready":
        raise HTTPException(
            status_code=409,
            detail=f"Part '{part_id}' is not ready (status='{part.status}').",
        )
    path_str = part.exports.get(fmt)
    if not path_str:
        raise HTTPException(
            status_code=404,
            detail=f"No {fmt.upper()} export found for part '{part_id}'.",
        )
    path = Path(path_str)
    if not path.exists():
        raise HTTPException(
            status_code=404,
            detail=f"{fmt.upper()} file missing on disk: {path}",
        )
    return FileResponse(
        path=str(path),
        media_type=_MEDIA_TYPES[fmt],
        filename=f"{part.name}_{part_id[:8]}.{fmt}",
    )


@router.get("/parts/{part_id}/step")
def get_step(
    part_id: str, manager: SessionManager = Depends(get_manager)
) -> FileResponse:
    """Download the STEP file for a ready part."""
    return _serve_export(part_id, "step", manager)


@router.get("/parts/{part_id}/stl")
def get_stl(
    part_id: str, manager: SessionManager = Depends(get_manager)
) -> FileResponse:
    """Download the STL file for a ready part."""
    return _serve_export(part_id, "stl", manager)
