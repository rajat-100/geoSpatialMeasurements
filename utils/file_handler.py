import os
import zipfile
import tempfile
from typing import Generator
from contextlib import contextmanager

import fiona

# ──────────────────────────────────────────────────────────────────────
# Phase 2: KML Configuration
# Fiona disables the KML/LIBKML drivers by default. We must explicitly
# enable them so that uploaded .kml files can be parsed by GeoPandas.
# ──────────────────────────────────────────────────────────────────────
if "KML" not in fiona.supported_drivers:
    fiona.drvsupport.supported_drivers["KML"] = "rw"
if "LIBKML" not in fiona.supported_drivers:
    fiona.drvsupport.supported_drivers["LIBKML"] = "rw"


class FileHandlingError(Exception):
    """Custom exception for file validation and extraction errors."""
    pass


def sanitize_filename(filename: str) -> str:
    """Strip directory components to prevent path-traversal attacks."""
    return os.path.basename(filename)


def locate_shapefile(extracted_dir: str) -> str:
    """
    Scans the extracted temporary directory to locate the .shp file.
    Ignores auxiliary files (.shx, .dbf, .prj) – they are kept in place
    so that GeoPandas can discover them automatically via sidecar lookup.

    Raises:
        FileHandlingError: If no .shp file is found in the archive.
    """
    shp_files = []
    for root, _, files in os.walk(extracted_dir):
        for fname in files:
            if fname.lower().endswith(".shp") and not fname.startswith("._"):
                shp_files.append(os.path.join(root, fname))

    if not shp_files:
        raise FileHandlingError(
            "No .shp file found inside the uploaded zip archive."
        )

    # When multiple shapefiles exist, prefer the shallowest one.
    shp_files.sort(key=lambda p: p.count(os.sep))
    return shp_files[0]


# ──────────────────────────────────────────────────────────────────────
# Phase 2: Zip Extraction Logic
# Uses tempfile.TemporaryDirectory so everything is cleaned up on exit.
# Defends against Zip-Slip (directory-traversal) vulnerabilities.
# ──────────────────────────────────────────────────────────────────────
@contextmanager
def extract_shapefile_zip(file_bytes: bytes) -> Generator[str, None, None]:
    """
    Securely extracts a zipped Shapefile into an isolated temp directory.
    Yields the absolute path to the discovered .shp file.
    """
    with tempfile.TemporaryDirectory(prefix="gspace_shp_") as temp_dir:
        zip_path = os.path.join(temp_dir, "upload.zip")
        with open(zip_path, "wb") as f:
            f.write(file_bytes)

        try:
            with zipfile.ZipFile(zip_path, "r") as zf:
                # Security: reject any member whose resolved path escapes temp_dir
                abs_temp = os.path.abspath(temp_dir) + os.sep
                for member in zf.namelist():
                    resolved = os.path.abspath(os.path.join(temp_dir, member))
                    if not resolved.startswith(abs_temp):
                        raise FileHandlingError(
                            f"Zip Slip detected – malicious path: {member}"
                        )
                zf.extractall(temp_dir)
        except zipfile.BadZipFile:
            raise FileHandlingError(
                "The uploaded file is not a valid .zip archive."
            )

        # Phase 2: Target Identification – locate the .shp inside the extract
        shp_path = locate_shapefile(temp_dir)
        yield shp_path


@contextmanager
def save_temp_kml(
    file_bytes: bytes, filename: str = "data.kml"
) -> Generator[str, None, None]:
    """
    Saves uploaded KML bytes to an isolated temporary file.
    Yields the path so GeoPandas can read it.
    """
    with tempfile.TemporaryDirectory(prefix="gspace_kml_") as temp_dir:
        clean_name = sanitize_filename(filename)
        if not clean_name.lower().endswith(".kml"):
            clean_name += ".kml"
        kml_path = os.path.join(temp_dir, clean_name)
        with open(kml_path, "wb") as f:
            f.write(file_bytes)
        yield kml_path


# ──────────────────────────────────────────────────────────────────────
# Unified entry-point: auto-detect file type and yield a readable path
# ──────────────────────────────────────────────────────────────────────
@contextmanager
def prepare_geospatial_file(
    filename: str, file_bytes: bytes
) -> Generator[str, None, None]:
    """
    Detects .zip (Shapefile) or .kml and yields a file path ready
    for geopandas.read_file().
    """
    lower = filename.lower()
    if lower.endswith(".zip"):
        with extract_shapefile_zip(file_bytes) as path:
            yield path
    elif lower.endswith(".kml"):
        with save_temp_kml(file_bytes, filename) as path:
            yield path
    else:
        raise FileHandlingError(
            f"Unsupported format '{filename}'. "
            "Upload a .zip (Shapefile) or .kml file."
        )
