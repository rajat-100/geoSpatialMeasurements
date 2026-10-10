# Gspace – Geospatial File Measurement API

A FastAPI backend designed to ingest geospatial files (ESRI Shapefiles in `.zip` archives and Google Earth `.kml` files), perform secure archive decompression, dynamically reproject geometries from angular degrees to localized metric UTM planes, and compute high-precision geometric measurements (area and length).

---

## 🌟 Key Features

1. **Secure File Ingestion**:
   - Defends against **Zip-Slip** directory-traversal vulnerabilities by validating normalized member paths.
   - Isolated temporary storage using Python's `tempfile.TemporaryDirectory` with automatic lifecycle cleanup.
   - Automatically enables Fiona's `KML` and `LIBKML` drivers at runtime.
2. **Accurate Projection Math**:
   - Detects geographic coordinate reference systems (e.g., `EPSG:4326` in degrees).
   - Dynamically determines the appropriate Cartesian projection using `gdf.estimate_utm_crs()` (with an `EPSG:3857` fallback) so calculations are in meters instead of degrees.
   - Computes area in metric units ($m^2$, $km^2$, hectares) and length in metric units ($m$, $km$).
3. **Data Persistence**:
   - Embedded SQLite storage layer for tracking uploads, metadata, status, summaries, and full per-feature GeoJSON measurements.
4. **Standard Python Architecture**:
   - Built with native FastAPI, Uvicorn, and GeoPandas without any container overhead.

---

## 🏗️ Project Architecture

```
Gspace/
├── main.py                     # FastAPI routes, CORS, lifespan startup
├── services/
│   ├── geo_processor.py        # Dynamic CRS transforms & polymorphic measurements
│   └── storage.py              # SQLite persistence for uploads & features
├── utils/
│   └── file_handler.py         # Zip-Slip defense, shapefile sidecar discovery, KML handling
├── tests/
│   └── test_gspace.py          # Pytest suite (11 unit/integration tests)
├── requirements.txt            # Python dependencies
└── README.md                   # System documentation
```

---

## 📐 Mathematical & Coordinate Transformation Logic

### The Problem with Angular Coordinates
Standard geographic coordinates ($latitude, longitude$) are represented in angular units (degrees) referencing an ellipsoid (e.g., WGS 84 / `EPSG:4326`). Direct Euclidean calculations ($\Delta x^2 + \Delta y^2$ or $\text{area}$) produce values in **square degrees**, which vary drastically in ground distance depending on latitude.

### Dynamic UTM Selection
When an uploaded dataset has a geographic CRS:
1. `gdf.estimate_utm_crs()` inspects the geometric centroid and bounding box.
2. It calculates the optimal 6-degree Universal Transverse Mercator (UTM) zone (e.g., `EPSG:32630` for UTM zone 30N).
3. The dataset is reprojected into that Cartesian metric system.
4. Calculations are performed:
   - **Polygon / MultiPolygon**: $\text{Area} = \iint dx\,dy$ ($m^2, km^2, \text{ha}$).
   - **LineString / MultiLineString**: $\text{Length} = \int \sqrt{dx^2 + dy^2}$ ($m, km$).
   - **Point / MultiPoint**: Safely flagged without false area/length metrics.

---

## 🚀 API Endpoints & Usage

### 1. Upload File (`POST /api/files/`)
Upload a `.zip` containing a Shapefile (with `.shp`, `.shx`, `.dbf`, `.prj`) or a `.kml` file.

```bash
curl -X POST "http://127.0.0.1:8000/api/files/" \
  -H "Accept: application/json" \
  -F "file=@boundaries.zip"
```

**Response (`201 Created`):**
```json
{
  "message": "File processed successfully.",
  "file": {
    "id": "a1b2c3d4",
    "filename": "boundaries.zip",
    "feature_count": 3,
    "crs": "EPSG:4326",
    "projected_crs": "EPSG:32630",
    "status": "COMPLETED",
    "created_at": "2026-10-10T05:20:00+00:00"
  },
  "summary": {
    "total_area_sq_m": 1245000.5,
    "total_area_sq_km": 1.245,
    "total_area_hectares": 124.5,
    "total_length_m": 0.0,
    "total_length_km": 0.0,
    "geometry_type_counts": {
      "Polygon": 3
    }
  }
}
```

### 2. List All Files (`GET /api/files/`)
```bash
curl -X GET "http://127.0.0.1:8000/api/files/"
```

### 3. File Summary (`GET /api/files/{file_id}/`)
```bash
curl -X GET "http://127.0.0.1:8000/api/files/a1b2c3d4/"
```

### 4. Detailed Feature Measurements (`GET /api/files/{file_id}/measurements/`)
Returns full GeoJSON features with calculated properties:
```bash
curl -X GET "http://127.0.0.1:8000/api/files/a1b2c3d4/measurements/"
```

---

## 💻 Running Locally

Start the development server with auto-reload:

```bash
.venv/bin/uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

- **Interactive Swagger UI**: [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)
- **Interactive ReDoc**: [http://127.0.0.1:8000/redoc](http://127.0.0.1:8000/redoc)

---

## 🧪 Running Tests

Execute the complete automated test suite:

```bash
.venv/bin/pytest tests/test_gspace.py -v
```
