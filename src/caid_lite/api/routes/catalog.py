"""GET /api/catalog and POST /api/catalog/insert — standard parts library."""

from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..deps import get_manager
from ...session.manager import SessionManager

router = APIRouter(tags=["catalog"])


class CatalogInsertRequest(BaseModel):
    """POST /api/catalog/insert request body."""

    type: str = Field(..., description="Catalog part type id, e.g. 'iso4762'")
    size: str = Field(..., description="Size label, e.g. 'M6'")
    length: Optional[float] = Field(
        None, gt=0, description="Length in mm (required for bolts/screws)"
    )


@router.get("/catalog", response_model=Dict[str, Any])
def get_catalog() -> Dict[str, Any]:
    """Return the full standard parts catalog grouped by category.

    Response shape::

        {
          "bolt": [
            {
              "id": "iso4762",
              "name": "ISO 4762 Socket Head Cap Screw",
              "has_length": true,
              "default_lengths": [5, 8, 10, ...],
              "sizes": ["M2", "M3", ...],
              "dims": {"M3": {"d": 3.0, "dk": 5.5, ...}, ...}
            },
            ...
          ],
          "nut": [...],
          "washer": [...]
        }
    """
    from ...catalog.data import get_catalog_by_category
    return get_catalog_by_category()


@router.post("/catalog/insert", response_model=Dict[str, Any])
async def insert_catalog_part(
    body: CatalogInsertRequest,
    manager: SessionManager = Depends(get_manager),
) -> Dict[str, Any]:
    """Instantiate a standard catalog part and add it to the parts shelf.

    Bypasses the LLM entirely — dimensions are read from ISO tables and
    a CadQuery script is executed directly in the sandbox.

    Returns the newly created ``PartEntry`` dict with ``status="generating"``.
    Progress is tracked via ``GET /api/events`` SSE stream.
    """
    try:
        part_id = await manager.insert_catalog_part(
            part_type=body.type,
            size=body.size,
            length=body.length,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    part = manager.get_part(part_id)
    if part is None:
        raise HTTPException(status_code=500, detail="Part creation failed unexpectedly.")
    return part.to_dict()
