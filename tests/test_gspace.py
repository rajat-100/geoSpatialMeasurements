import io
import os
import zipfile
import pytest
from fastapi.testclient import TestClient
import geopandas as gpd
from shapely.geometry import Polygon, LineString, Point

from main import app
from utils.file_handler import extract_shapefile_zip, save_temp_kml, FileHandlingError
from services.geo_processor import process_geospatial_file
from services.storage import init_db

client = TestClient(app)


@pytest.fixture(autouse=True)
def setup_test_db(tmp_path, monkeypatch):
    """Use a temporary database for test runs."""
    test_db = str(tmp_path / "test_geospatial.db")
    monkeypatch.setenv("GSPACE_DB_PATH", test_db)
    init_db(test_db)


def create_sample_shapefile_zip(geom_type: str = "polygon") -> bytes:
    """Helper to generate a zipped shapefile in-memory."""
    if geom_type == "polygon":
        # Square near London (WGS84 degrees): ~0.01 deg x 0.01 deg
        geom = Polygon([(-0.1, 51.5), (-0.1, 51.51), (-0.09, 51.51), (-0.09, 51.5), (-0.1, 51.5)])
    elif geom_type == "line":
        geom = LineString([(-0.1, 51.5), (-0.1, 51.52)])
    else:
        geom = Point(-0.1, 51.5)

    gdf = gpd.GeoDataFrame([{"name": "test_feature", "geometry": geom}], crs="EPSG:4326")

    # Write to zip in memory
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            shp_path = os.path.join(td, "test_layer.shp")
            gdf.to_file(shp_path)
            for fname in os.listdir(td):
                full_path = os.path.join(td, fname)
                zf.write(full_path, arcname=fname)
    buf.seek(0)
    return buf.getvalue()


def create_sample_kml() -> bytes:
    """Helper to generate a minimal valid KML string."""
    kml_content = """<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <name>Sample Layer</name>
    <Placemark>
      <name>Sample Polygon</name>
      <Polygon>
        <outerBoundaryIs>
          <LinearRing>
            <coordinates>
              77.2090,28.6139,0
              77.2190,28.6139,0
              77.2190,28.6239,0
              77.2090,28.6239,0
              77.2090,28.6139,0
            </coordinates>
          </LinearRing>
        </outerBoundaryIs>
      </Polygon>
    </Placemark>
  </Document>
</kml>"""
    return kml_content.encode("utf-8")


# ── Phase 2 Tests: File Handling & Security ──────────────────────────

def test_zip_extraction_success():
    zip_bytes = create_sample_shapefile_zip("polygon")
    with extract_shapefile_zip(zip_bytes) as shp_path:
        assert os.path.exists(shp_path)
        assert shp_path.endswith(".shp")


def test_zip_slip_prevention():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("../../etc/passwd", "malicious payload")
    buf.seek(0)
    with pytest.raises(FileHandlingError, match="Zip Slip"):
        with extract_shapefile_zip(buf.getvalue()):
            pass


def test_missing_shp_in_zip():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("test.txt", "not a shapefile")
    buf.seek(0)
    with pytest.raises(FileHandlingError, match="No .shp file found"):
        with extract_shapefile_zip(buf.getvalue()):
            pass


def test_kml_save():
    kml_bytes = create_sample_kml()
    with save_temp_kml(kml_bytes, "test.kml") as path:
        assert os.path.exists(path)
        assert path.endswith(".kml")


# ── Phase 3 Tests: Geo Processor & Measurements ──────────────────────

def test_polygon_measurement_utm_reprojection():
    zip_bytes = create_sample_shapefile_zip("polygon")
    with extract_shapefile_zip(zip_bytes) as shp_path:
        result = process_geospatial_file(shp_path)

        assert result["feature_count"] == 1
        assert "WGS 84" in result["crs"] or "4326" in result["crs"]
        assert "UTM" in result["projected_crs"] or "326" in result["projected_crs"] or "3857" in result["projected_crs"]

        feat = result["features"][0]
        assert feat["geometry_type"] == "Polygon"
        assert feat["measurements"]["area_sq_m"] > 0
        assert feat["measurements"]["area_sq_km"] > 0
        assert feat["measurements"]["area_hectares"] > 0

        summary = result["summary"]
        assert summary["total_area_sq_m"] > 0
        assert summary["geometry_type_counts"]["Polygon"] == 1


def test_line_measurement():
    zip_bytes = create_sample_shapefile_zip("line")
    with extract_shapefile_zip(zip_bytes) as shp_path:
        result = process_geospatial_file(shp_path)
        feat = result["features"][0]
        assert feat["geometry_type"] == "LineString"
        assert feat["measurements"]["length_m"] > 0
        assert feat["measurements"]["length_km"] > 0
        assert result["summary"]["total_length_m"] > 0


def test_point_measurement():
    zip_bytes = create_sample_shapefile_zip("point")
    with extract_shapefile_zip(zip_bytes) as shp_path:
        result = process_geospatial_file(shp_path)
        feat = result["features"][0]
        assert feat["geometry_type"] == "Point"
        assert feat["measurements"]["area_sq_m"] is None
        assert feat["measurements"]["length_m"] is None


# ── Phase 4 Tests: API Endpoints ─────────────────────────────────────

def test_api_upload_shapefile():
    zip_bytes = create_sample_shapefile_zip("polygon")
    response = client.post(
        "/api/files/",
        files={"file": ("london_poly.zip", zip_bytes, "application/zip")},
    )
    assert response.status_code == 201
    data = response.json()
    assert "file" in data
    file_id = data["file"]["id"]
    assert data["file"]["feature_count"] == 1
    assert data["summary"]["total_area_sq_m"] > 0

    # Test GET /api/files/
    list_res = client.get("/api/files/")
    assert list_res.status_code == 200
    files = list_res.json()["files"]
    assert any(f["id"] == file_id for f in files)

    # Test GET /api/files/{id}/
    detail_res = client.get(f"/api/files/{file_id}/")
    assert detail_res.status_code == 200
    assert detail_res.json()["file"]["id"] == file_id

    # Test GET /api/files/{id}/measurements/
    measure_res = client.get(f"/api/files/{file_id}/measurements/")
    assert measure_res.status_code == 200
    m_data = measure_res.json()
    assert len(m_data["features"]) == 1
    assert m_data["features"][0]["geometry"]["type"] == "Polygon"


def test_api_upload_kml():
    kml_bytes = create_sample_kml()
    response = client.post(
        "/api/files/",
        files={"file": ("delhi_poly.kml", kml_bytes, "application/vnd.google-earth.kml+xml")},
    )
    assert response.status_code == 201
    data = response.json()
    assert data["file"]["feature_count"] == 1
    assert data["summary"]["total_area_sq_m"] > 0


def test_api_invalid_file_extension():
    response = client.post(
        "/api/files/",
        files={"file": ("test.txt", b"plain text", "text/plain")},
    )
    assert response.status_code == 400
    assert "Unsupported file type" in response.json()["detail"]


def test_api_file_not_found():
    response = client.get("/api/files/nonexistent_id/")
    assert response.status_code == 404
