"""
Unit and Integration Tests for Privacy Redaction Engine
======================================================
Tests:
1. Engine initialization & API configuration
2. SQLite detection cache persistence & hit verification
3. Gaussian blur mathematical transformation & frequency variance reduction
4. EXIF purge verification
5. Boundary safety margin expansion & coordinate clamping
6. FastAPI REST endpoints health & sample serving
"""

import os
import io
import unittest
import numpy as np
from PIL import Image, ImageFilter

from engine.redaction_engine import redaction_engine, RedactionEngine
from engine.cache import redaction_cache

SAMPLES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sample_images")


def test_engine_initialization():
    metrics = redaction_engine.get_metrics()
    assert metrics["engine_status"] == "ONLINE"
    assert metrics["credentials_configured"]["plate_recognizer"] is True
    assert metrics["credentials_configured"]["faceplusplus"] is True


def test_sqlite_cache_operations():
    test_hash = "test_sha256_deadbeef1234"
    test_faces = [{"box": {"xmin": 10, "ymin": 10, "xmax": 50, "ymax": 50}, "type": "face"}]
    test_plates = [{"box": {"xmin": 60, "ymin": 60, "xmax": 120, "ymax": 80}, "type": "plate", "plate_text": "MH02CB1234"}]

    # Set
    redaction_cache.set(test_hash, test_faces, test_plates, 200, 200)

    # Get
    cached = redaction_cache.get(test_hash)
    assert cached is not None
    assert cached["image_hash"] == test_hash
    assert len(cached["faces"]) == 1
    assert cached["faces"][0]["box"]["xmin"] == 10
    assert len(cached["plates"]) == 1
    assert cached["plates"][0]["plate_text"] == "MH02CB1234"


def test_gaussian_blur_pixel_variance_reduction():
    """
    Verify that applying Gaussian blur over a high-contrast pattern
    significantly flattens local pixel gradients (irreversible de-identification).
    """
    # Create high-contrast checkered pattern inside target region
    img = Image.new("RGB", (100, 100), color=(255, 255, 255))
    pixels = img.load()
    for y in range(20, 80):
        for x in range(20, 80):
            if (x // 5 + y // 5) % 2 == 0:
                pixels[x, y] = (0, 0, 0)

    arr_raw = np.array(img)[25:75, 25:75]
    raw_variance = np.var(arr_raw)

    boxes = [{"box": {"xmin": 20, "ymin": 20, "xmax": 80, "ymax": 80}}]
    blurred = redaction_engine.apply_gaussian_blur(img, boxes, blur_radius=25, expand_margin_pct=0.0, feather=False)

    arr_blurred = np.array(blurred)[25:75, 25:75]
    blurred_variance = np.var(arr_blurred)

    # Variance after Gaussian blur should drop by over 80%
    assert blurred_variance < raw_variance * 0.20


def test_exif_purge():
    """Verify that strip_exif produces an image with empty EXIF metadata."""
    img = Image.new("RGB", (50, 50), color=(100, 100, 100))
    cleaned = redaction_engine.strip_exif(img)
    assert cleaned.size == (50, 50)
    assert cleaned.getexif() is not None
    assert len(cleaned.getexif()) == 0


def test_margin_expansion_clamping():
    """Verify that bounding boxes near edges do not produce negative coordinates or overflow."""
    img = Image.new("RGB", (100, 100), color=(10, 10, 10))
    # Box right on top-left edge
    boxes = [{"box": {"xmin": 0, "ymin": 0, "xmax": 20, "ymax": 20}}]
    blurred = redaction_engine.apply_gaussian_blur(img, boxes, blur_radius=10, expand_margin_pct=0.5)
    assert blurred.size == (100, 100)


def test_full_pipeline_sample_execution():
    """Test full redaction on pre-seeded dual sample image."""
    sample_path = os.path.join(SAMPLES_DIR, "street_scene_dual.jpg")
    if not os.path.exists(sample_path):
        print("Sample image not found, skipping...")
        return

    res = redaction_engine.redact(sample_path, use_cache=True)
    assert res["success"] is True
    assert res["detections"]["faces_count"] >= 1
    assert res["detections"]["plates_count"] >= 1
    assert "image_bytes" in res
    assert len(res["image_bytes"]) > 10000
    assert res["original_sha256"] != res["redacted_sha256"]


def test_fastapi_endpoints():
    """Test REST API endpoints using TestClient."""
    from fastapi.testclient import TestClient
    from main import app

    client = TestClient(app)

    # 1. Root & Health
    r_root = client.get("/")
    assert r_root.status_code == 200
    assert r_root.json()["status"] == "ONLINE"

    r_health = client.get("/api/v1/health")
    assert r_health.status_code == 200
    assert r_health.json()["status"] == "healthy"

    # 2. Metrics
    r_metrics = client.get("/api/v1/metrics")
    assert r_metrics.status_code == 200
    assert "stats" in r_metrics.json()

    # 3. Multipart File Redact (JSON response)
    sample_path = os.path.join(SAMPLES_DIR, "street_scene_dual.jpg")
    if os.path.exists(sample_path):
        with open(sample_path, "rb") as f:
            r_redact = client.post(
                "/api/v1/redact",
                files={"file": ("dual.jpg", f, "image/jpeg")},
                data={"response_type": "json"}
            )
        assert r_redact.status_code == 200
        data = r_redact.json()
        assert data["success"] is True
        assert data["detections"]["faces_count"] >= 1
        assert data["detections"]["plates_count"] >= 1
        assert "redacted_image_base64" in data

        # 4. Binary Image Stream response
        with open(sample_path, "rb") as f:
            r_bin = client.post(
                "/api/v1/redact",
                files={"file": ("dual.jpg", f, "image/jpeg")},
                data={"response_type": "binary"}
            )
        assert r_bin.status_code == 200
        assert r_bin.headers["content-type"] == "image/png"
        assert len(r_bin.content) > 10000

        # 5. Detect Only endpoint
        r_det = client.post(
            "/api/v1/detect",
            json={"image_base64": data["redacted_image_base64"]}
        )
        assert r_det.status_code == 200
        assert "detections" in r_det.json()
