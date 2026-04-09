"""GET/PATCH/DELETE /api/parts — parts shelf CRUD."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any, Dict, List, Union

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel

from ..deps import get_manager
from ...session.manager import SessionManager


class PartPatch(BaseModel):
    name: str


class RefineRequest(BaseModel):
    """POST /api/parts/{id}/refine 요청 바디.

    Pydantic이 Union[int, float] 타입으로 string 값을 자동 거부하므로
    geometry_type 등의 string constraint 필드를 우발적으로 덮어쓰는 것을 방지한다.
    """

    constraints: Dict[str, Union[int, float]]

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


@router.patch("/parts/{part_id}", response_model=Dict[str, Any])
def patch_part(
    part_id: str,
    body: PartPatch,
    manager: SessionManager = Depends(get_manager),
) -> Dict[str, Any]:
    """Rename a part."""
    if not manager.rename_part(part_id, body.name):
        raise HTTPException(status_code=404, detail=f"Part '{part_id}' not found.")
    part = manager.get_part(part_id)
    return part.to_dict()  # type: ignore[union-attr]


@router.delete("/parts/{part_id}", status_code=204)
def delete_part(
    part_id: str, manager: SessionManager = Depends(get_manager)
) -> None:
    """Remove a part from the shelf."""
    if not manager.remove_part(part_id):
        raise HTTPException(status_code=404, detail=f"Part '{part_id}' not found.")


@router.post("/parts/import", response_model=Dict[str, Any])
async def import_part(
    file: UploadFile = File(..., description="STEP (.step/.stp) or STL (.stl) file"),
    manager: SessionManager = Depends(get_manager),
) -> Dict[str, Any]:
    """Import an existing STEP or STL file as a new part on the shelf.

    The file is saved to a temporary upload directory, then processed in
    a subprocess (geometry validation + normalised STEP+STL export).
    Returns immediately with ``status="generating"``; track progress via SSE.
    """
    filename = file.filename or "upload"
    ext = Path(filename).suffix.lower()
    if ext in (".step", ".stp"):
        fmt = "step"
    elif ext == ".stl":
        fmt = "stl"
    else:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type '{ext}'. Only STEP (.step/.stp) and STL (.stl) are accepted.",
        )

    # Save upload to a stable path so the subprocess can read it
    upload_dir = manager._pipeline._sandbox.output_dir / "_uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    tmp_name = f"{uuid.uuid4().hex}{ext}"
    save_path = upload_dir / tmp_name
    content = await file.read()
    save_path.write_bytes(content)

    # Derive display name from filename (strip extension)
    name = Path(filename).stem

    try:
        part_id = await manager.import_file(
            source_path=str(save_path),
            name=name,
            source_format=fmt,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    part = manager.get_part(part_id)
    if part is None:
        raise HTTPException(status_code=500, detail="Part creation failed unexpectedly.")
    return part.to_dict()


@router.post("/parts/{part_id}/refine", response_model=Dict[str, Any])
async def refine_part(
    part_id: str,
    body: RefineRequest,
    manager: SessionManager = Depends(get_manager),
) -> Dict[str, Any]:
    """Update a part's numeric constraints and restart generation from the Designer.

    Skips ArchitectAgent — reuses the stored DesignPlan with merged constraints.
    Returns the updated PartEntry immediately; status will be ``"generating"``.
    Progress is tracked via ``GET /api/events`` SSE stream.
    """
    try:
        await manager.modify_constraints(part_id, dict(body.constraints))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    part = manager.get_part(part_id)
    if part is None:
        raise HTTPException(status_code=404, detail=f"Part '{part_id}' not found.")
    return part.to_dict()
