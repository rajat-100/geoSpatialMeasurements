"""
Phase 3: The Projection & Measurement Engine
─────────────────────────────────────────────
1. Reads geospatial data into a GeoDataFrame.
2. Detects whether the CRS is geographic (degrees).
3. If geographic → reprojects to localised metric UTM via estimate_utm_crs().
4. Iterates features and computes area / length by geometry type.
"""

import math
from typing import Any, Dict, List

import geopandas as gpd
import numpy as np
from shapely.geometry import mapping


class GeoProcessingError(Exception):
    """Raised when geospatial processing fails."""
    pass


# ──────────────────────────────────────────────
# Internal helpers
# ──────────────────────────────────────────────

def _clean_properties(row_dict: Dict[str, Any]) -> Dict[str, Any]:
    """
    Sanitise attribute fields for JSON serialisation:
    - Drops the 'geometry' key (returned separately).
    - Converts NaN / Inf → None.
    - Formats datetime objects to ISO strings.
    """
    cleaned: Dict[str, Any] = {}
    for key, value in row_dict.items():
        if key == "geometry":
            continue
        if value is None:
            cleaned[key] = None
        elif isinstance(value, (float, np.floating)):
            cleaned[key] = None if (math.isnan(value) or math.isinf(value)) else float(value)
        elif isinstance(value, (int, np.integer)):
            cleaned[key] = int(value)
        elif hasattr(value, "isoformat"):
            cleaned[key] = value.isoformat()
        else:
            cleaned[key] = str(value)
    return cleaned


def _crs_label(crs) -> str:
    """Return a human-readable CRS string."""
    if crs is None:
        return "Unknown"
    try:
        return crs.to_string()
    except Exception:
        return str(crs)


# ──────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────

def process_geospatial_file(file_path: str) -> Dict[str, Any]:
    """
    Full processing pipeline:
      file_path → GeoDataFrame → CRS transform → measure → dict
    """

    # ── Step 1: DataFrame Ingestion ──────────────────────────────────
    try:
        gdf = gpd.read_file(file_path)
    except Exception as exc:
        raise GeoProcessingError(
            f"Failed to read geospatial file: {exc}"
        )

    if gdf.empty:
        return _empty_result()

    # ── Step 2: CRS detection & fallback ─────────────────────────────
    if gdf.crs is None:
        gdf = gdf.set_crs("EPSG:4326")

    original_crs = _crs_label(gdf.crs)

    # ── Step 3: Dynamic CRS Transformation ───────────────────────────
    # If the CRS is geographic (coordinates in degrees), measurements
    # using .area / .length would return values in degree² / degrees –
    # which is WRONG.  We reproject to a local metric UTM zone.
    projected_gdf = gdf
    projected_crs = original_crs

    if gdf.crs and gdf.crs.is_geographic:
        try:
            utm = gdf.estimate_utm_crs()
            if utm is not None:
                projected_gdf = gdf.to_crs(utm)
                projected_crs = _crs_label(utm)
            else:
                projected_gdf = gdf.to_crs("EPSG:3857")
                projected_crs = "EPSG:3857 (fallback)"
        except Exception:
            try:
                projected_gdf = gdf.to_crs("EPSG:3857")
                projected_crs = "EPSG:3857 (fallback)"
            except Exception:
                pass  # keep original; measurements will be in degrees

    # ── Step 4: Feature Iteration & Geometry Logic ───────────────────
    features: List[Dict[str, Any]] = []
    total_area_m2 = 0.0
    total_length_m = 0.0
    geom_counts: Dict[str, int] = {}

    for idx, orig_row in gdf.iterrows():
        proj_row = projected_gdf.loc[idx]
        geom = orig_row.geometry
        proj_geom = proj_row.geometry

        geom_type = geom.geom_type if geom is not None else "None"
        geom_counts[geom_type] = geom_counts.get(geom_type, 0) + 1

        measurements = _measure(proj_geom, geom_type)

        if measurements.get("area_sq_m") is not None:
            total_area_m2 += measurements["area_sq_m"]
        if measurements.get("length_m") is not None:
            total_length_m += measurements["length_m"]

        features.append({
            "feature_id": int(idx) if isinstance(idx, (int, np.integer)) else str(idx),
            "geometry_type": geom_type,
            "geometry": mapping(geom) if geom is not None else None,
            "crs": original_crs,
            "projected_crs": projected_crs,
            "measurements": measurements,
            "properties": _clean_properties(orig_row.to_dict()),
        })

    return {
        "feature_count": len(features),
        "crs": original_crs,
        "projected_crs": projected_crs,
        "features": features,
        "summary": {
            "total_area_sq_m": round(total_area_m2, 2),
            "total_area_sq_km": round(total_area_m2 / 1_000_000, 6),
            "total_area_hectares": round(total_area_m2 / 10_000, 4),
            "total_length_m": round(total_length_m, 2),
            "total_length_km": round(total_length_m / 1_000, 4),
            "geometry_type_counts": geom_counts,
        },
    }


# ──────────────────────────────────────────────
# Measurement dispatcher
# ──────────────────────────────────────────────

def _measure(proj_geom, geom_type: str) -> Dict[str, Any]:
    """
    Compute area or length depending on the geometry type.
    - Polygon / MultiPolygon  → area  (m², km², hectares)
    - LineString / MultiLineString → length (m, km)
    - Point / MultiPoint → no measurement (None)
    """
    result: Dict[str, Any] = {
        "area_sq_m": None,
        "area_sq_km": None,
        "area_hectares": None,
        "length_m": None,
        "length_km": None,
        "supported": True,
        "notes": None,
    }

    if proj_geom is None or proj_geom.is_empty:
        result["supported"] = False
        result["notes"] = "Empty or null geometry."
        return result

    if geom_type in ("Polygon", "MultiPolygon"):
        area = float(proj_geom.area)
        result["area_sq_m"] = round(area, 2)
        result["area_sq_km"] = round(area / 1_000_000, 6)
        result["area_hectares"] = round(area / 10_000, 4)

    elif geom_type in ("LineString", "MultiLineString"):
        length = float(proj_geom.length)
        result["length_m"] = round(length, 2)
        result["length_km"] = round(length / 1_000, 4)

    elif geom_type in ("Point", "MultiPoint"):
        result["notes"] = "Point geometry – no area or length measurement."

    else:
        result["supported"] = False
        result["notes"] = f"Geometry type '{geom_type}' is not supported for measurements."

    return result


def _empty_result() -> Dict[str, Any]:
    """Return a valid but empty processing result."""
    return {
        "feature_count": 0,
        "crs": "Unknown",
        "projected_crs": "Unknown",
        "features": [],
        "summary": {
            "total_area_sq_m": 0.0,
            "total_area_sq_km": 0.0,
            "total_area_hectares": 0.0,
            "total_length_m": 0.0,
            "total_length_km": 0.0,
            "geometry_type_counts": {},
        },
    }
