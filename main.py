"""
Gspace – Geospatial File Measurement API
─────────────────────────────────────────
Phase 4: API Wiring

Endpoints:
  POST   /api/files/                  – Upload .zip (Shapefile) or .kml
  GET    /api/files/                  – List all uploaded files
  GET    /api/files/{file_id}/        – File metadata & summary
  GET    /api/files/{file_id}/measurements/  – Full feature measurements
"""

from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from utils.file_handler import prepare_geospatial_file, FileHandlingError
from services.geo_processor import process_geospatial_file, GeoProcessingError
from services.storage import (
    init_db,
    save_processed_file,
    get_file_by_id,
    get_file_measurements,
    list_files,
)

from contextlib import asynccontextmanager


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Ensure the database table exists on application boot."""
    init_db()
    yield


# ── App initialisation ──────────────────────────────────────────────
app = FastAPI(
    title="Gspace – Geospatial File Measurement API",
    description=(
        "Upload ESRI Shapefiles (.zip) or KML files and receive "
        "accurate area / length measurements computed in a locally "
        "projected metric CRS."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

# Allow CORS for local / frontend development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── POST /api/files/ ────────────────────────────────────────────────
@app.post("/api/files/", status_code=201)
async def upload_file(file: UploadFile = File(...)):
    """
    Upload a geospatial file for processing.

    Accepted formats:
    - `.zip` archive containing an ESRI Shapefile (.shp + sidecar files)
    - `.kml` (Keyhole Markup Language)

    The file is extracted securely, parsed into a GeoDataFrame,
    reprojected to a metric CRS if necessary, and measured.
    """
    filename = file.filename or "unknown"

    # Validate content type / extension early
    lower = filename.lower()
    if not (lower.endswith(".zip") or lower.endswith(".kml")):
        raise HTTPException(
            status_code=400,
            detail=(
                f"Unsupported file type '{filename}'. "
                "Please upload a .zip (Shapefile) or .kml file."
            ),
        )

    # Read file bytes
    try:
        file_bytes = await file.read()
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Failed to read upload: {exc}")
    finally:
        await file.close()

    if not file_bytes:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

    # ── Pipeline: file_handler → geo_processor → storage ────────────
    try:
        with prepare_geospatial_file(filename, file_bytes) as geo_path:
            result = process_geospatial_file(geo_path)
    except FileHandlingError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except GeoProcessingError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Unexpected processing error: {exc}",
        )

    # Persist to SQLite
    record = save_processed_file(
        filename=filename,
        feature_count=result["feature_count"],
        crs=result["crs"],
        projected_crs=result["projected_crs"],
        features=result["features"],
        summary=result["summary"],
    )

    return {
        "message": "File processed successfully.",
        "file": record,
        "summary": result["summary"],
    }


# ── GET /api/files/ ─────────────────────────────────────────────────
@app.get("/api/files/")
async def get_files():
    """List all uploaded geospatial files."""
    return {"files": list_files()}


# ── GET /api/files/{file_id}/ ────────────────────────────────────────
@app.get("/api/files/{file_id}/")
async def get_file(file_id: str):
    """Retrieve metadata and summary for a specific file."""
    record = get_file_by_id(file_id)
    if record is None:
        raise HTTPException(status_code=404, detail="File not found.")
    return {"file": record}


# ── GET /api/files/{file_id}/measurements/ ───────────────────────────
@app.get("/api/files/{file_id}/measurements/")
async def get_measurements(file_id: str):
    """
    Retrieve the detailed per-feature measurements for a file,
    including geometry GeoJSON, CRS info, and attribute properties.
    """
    record = get_file_measurements(file_id)
    if record is None:
        raise HTTPException(status_code=404, detail="File not found.")
    return record
