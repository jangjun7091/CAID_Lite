"""GET/DELETE /api/parts — parts shelf CRUD."""

from __future__ import annotations

from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException

from ..deps import get_manager
from ...session.manager import SessionManager

router = APIRouter(tags=["parts"])


@router.get("/parts", response_model=List[Dict[str, Any]])
def get_parts(manager: SessionManager = Depends(get_manager)) -> List[Dict[str, Any]]:
    """Return all parts on the shelf, ordered by creation time (oldest first)."""
    return [p.to_dict() for p in manager.get_parts()]


@router.get("/parts/{part_id}", response_model=Dict[str, Any])
def get_part(
    part_id: str, manager: SessionManager = Depends(get_manager)
) -> Dict[str, Any]:
    """Return a single part by id."""
    part = manager.get_part(part_id)
    if part is None:
        raise HTTPException(status_code=404, detail=f"Part '{part_id}' not found.")
    return part.to_dict()


@router.delete("/parts/{part_id}", status_code=204)
def delete_part(
    part_id: str, manager: SessionManager = Depends(get_manager)
) -> None:
    """Remove a part from the shelf."""
    if not manager.remove_part(part_id):
        raise HTTPException(status_code=404, detail=f"Part '{part_id}' not found.")
