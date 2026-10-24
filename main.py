"""
Privacy Redaction Engine — Backend REST API
===========================================
Headless, high-throughput microservice backend for websites to identify and
redact human faces and vehicle license plates with Gaussian blur.

Endpoints:
- POST /api/v1/redact        : Redact image (multipart file upload, image URL, or base64)
- POST /api/v1/redact/json   : Redact image via JSON request body
- POST /api/v1/detect        : Bounding box detection only (no pixel modification)
- GET  /api/v1/health        : Health check & API credentials status
- GET  /api/v1/metrics       : Performance telemetry & cache diagnostics
- POST /api/v1/cache/clear   : Clear SHA-256 detection cache
- GET  /docs                 : Interactive Swagger OpenAPI documentation
"""

import os
import sys
import io
import base64
from typing import Optional, List, Dict, Any
from contextlib import asynccontextmanager

from dotenv import load_dotenv
load_dotenv()

# Safe console encoding for Windows terminals
if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

from fastapi import FastAPI, File, UploadFile, Form, HTTPException, Query, Response, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, HttpUrl

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from engine.redaction_engine import redaction_engine
from engine.cache import redaction_cache


@asynccontextmanager
async def lifespan(app: FastAPI):
    print("=" * 68)
    print("  [BACKEND READY] Privacy Redaction Engine REST Service")
    print("  Plate Recognizer API: CONFIGURED (Token: efabb54d...)")
    print("  Face++ Detection API: CONFIGURED (Key: I9J_x0mJ...)")
    print("  Redaction Kernel:     Adaptive Gaussian Blur + EXIF Purge")
    print("  OpenAPI Docs:         http://localhost:8002/docs")
    print("=" * 68)
    yield
    print("  [STOP] Privacy Redaction Engine shutting down.")


app = FastAPI(
    title="Privacy Redaction Engine API",
    description="""
Headless backend API to identify and redact human faces and vehicle license plates.
Combines **Plate Recognizer Snapshot API** and **Face++ Detection API** with
adaptive Gaussian blur, boundary safety padding, 100% EXIF stripping, and SQLite SHA-256 caching.
    """,
    version="2.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan
)

# Enable CORS for external websites and web applications
ALLOWED_ORIGINS = os.getenv("CORS_ORIGINS", "*").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# -----------------------------------------------------------------------------
# Request & Response Schemas
# -----------------------------------------------------------------------------

class RedactJsonRequest(BaseModel):
    image_base64: Optional[str] = Field(None, description="Base64 encoded image string or data URL")
    image_url: Optional[str] = Field(None, description="Publicly accessible HTTP/HTTPS URL of the image")
    blur_radius: Optional[int] = Field(None, description="Gaussian blur radius in px (e.g. 25). If null, scales adaptively (35%).")
    expand_margin_pct: float = Field(0.12, description="Safety boundary padding fraction (e.g. 0.12 = 12%)")
    redact_faces: bool = Field(True, description="Whether to redact human faces")
    redact_plates: bool = Field(True, description="Whether to redact vehicle license plates")
    feather: bool = Field(True, description="Whether to apply anti-aliased feathered mask edge")
    strip_exif: bool = Field(True, description="Whether to purge 100% of camera/GPS EXIF metadata")
    use_cache: bool = Field(True, description="Whether to check SQLite SHA-256 detection cache")
    output_format: str = Field("PNG", description="Output format: PNG, JPEG, WEBP")


class DetectJsonRequest(BaseModel):
    image_base64: Optional[str] = Field(None, description="Base64 encoded image string or data URL")
    image_url: Optional[str] = Field(None, description="Publicly accessible HTTP/HTTPS URL of the image")
    use_cache: bool = Field(True, description="Whether to check SQLite SHA-256 detection cache")


# -----------------------------------------------------------------------------
# API Endpoints
# -----------------------------------------------------------------------------

@app.get("/", summary="API Root", tags=["System"])
def root():
    return {
        "service": "Privacy Redaction Engine Backend API",
        "version": "2.0.0",
        "status": "ONLINE",
        "docs": "/docs",
        "redoc": "/redoc",
        "endpoints": {
            "redact_multipart": "POST /api/v1/redact",
            "redact_json": "POST /api/v1/redact/json",
            "detect_only": "POST /api/v1/detect",
            "health": "GET /api/v1/health",
            "metrics": "GET /api/v1/metrics"
        }
    }


@app.get("/api/v1/health", summary="Health Check", tags=["System"])
def health_check():
    return {
        "status": "healthy",
        "plate_recognizer_configured": bool(redaction_engine.plate_token),
        "faceplusplus_configured": bool(redaction_engine.face_key and redaction_engine.face_secret),
        "default_blur_radius": redaction_engine.default_blur_radius,
        "default_margin_pct": redaction_engine.default_margin_pct,
        "feather_edges": redaction_engine.feather_edges,
        "sqlite_cached_entries": redaction_cache.stats()["cached_items"]
    }


@app.get("/api/v1/metrics", summary="Operational Metrics", tags=["System"])
def get_metrics():
    return redaction_engine.get_metrics()


@app.post("/api/v1/cache/clear", summary="Clear Detection Cache", tags=["System"])
def clear_cache():
    redaction_cache.clear()
    return {"message": "SQLite detection cache cleared successfully"}


@app.post("/api/v1/redact", summary="Redact Image (Multipart Form or URL)", tags=["Redaction"])
async def redact_image_form(
    file: Optional[UploadFile] = File(None, description="Image file binary upload"),
    image_url: Optional[str] = Form(None, description="Public HTTP/HTTPS image URL"),
    image_base64: Optional[str] = Form(None, description="Base64 encoded image string"),
    blur_radius: Optional[int] = Form(None, description="Gaussian blur radius in px (default: adaptive 35%)"),
    expand_margin_pct: float = Form(0.12, description="Boundary margin expansion fraction (default: 0.12)"),
    redact_faces: bool = Form(True, description="Redact human faces via Face++"),
    redact_plates: bool = Form(True, description="Redact vehicle license plates via Plate Recognizer"),
    feather: bool = Form(True, description="Smooth feathered boundary blending"),
    strip_exif: bool = Form(True, description="Purge 100% of EXIF / GPS metadata"),
    use_cache: bool = Form(True, description="Use SQLite SHA-256 detection cache"),
    response_type: str = Form("json", description="Response type: 'json' (metadata + base64) or 'binary' (raw image stream)"),
    output_format: str = Form("PNG", description="Output image format: PNG, JPEG, WEBP")
):
    """
    Main redaction endpoint for websites and applications.
    Accepts image file upload, external image URL, or base64.
    Returns either a JSON response with detection telemetry and base64 image,
    or a raw binary image stream for direct embedding.
    """
    raw_bytes: bytes = b""

    if file is not None and file.filename:
        raw_bytes = await file.read()
    elif image_url:
        try:
            import requests
            headers = {"User-Agent": "Mozilla/5.0 PrivacyRedactionEngine/2.0"}
            r = requests.get(image_url, headers=headers, timeout=20)
            if r.status_code != 200:
                raise HTTPException(status_code=400, detail=f"Failed to fetch image from URL: HTTP {r.status_code}")
            raw_bytes = r.content
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Failed to download image from URL: {str(e)}")
    elif image_base64:
        try:
            clean_b64 = image_base64.split(",", 1)[1] if "," in image_base64 else image_base64
            raw_bytes = base64.b64decode(clean_b64)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Invalid base64 payload: {str(e)}")
    else:
        raise HTTPException(status_code=400, detail="Must provide one of: file, image_url, or image_base64")

    if len(raw_bytes) == 0:
        raise HTTPException(status_code=400, detail="Provided image data is empty")

    try:
        res = redaction_engine.redact(
            raw_bytes,
            redact_faces=redact_faces,
            redact_plates=redact_plates,
            blur_radius=blur_radius,
            expand_margin_pct=expand_margin_pct,
            feather=feather,
            strip_exif=strip_exif,
            use_cache=use_cache,
            output_format=output_format
        )

        # Return raw binary stream if requested
        if response_type.lower() == "binary":
            media_type = f"image/{output_format.lower()}"
            return Response(
                content=res["image_bytes"],
                media_type=media_type,
                headers={
                    "X-Faces-Redacted": str(res["detections"]["faces_count"]),
                    "X-Plates-Redacted": str(res["detections"]["plates_count"]),
                    "X-Original-SHA256": res["original_sha256"],
                    "X-Redacted-SHA256": res["redacted_sha256"],
                    "X-Detection-Latency-Ms": str(res["telemetry"]["detection_latency_ms"]),
                    "X-Blur-Latency-Ms": str(res["telemetry"]["blur_latency_ms"]),
                    "X-Cache-Hit": str(res["telemetry"]["cache_hit"]).lower()
                }
            )

        # Default JSON response
        fmt = output_format.lower()
        mime = f"image/{fmt}"
        b64_out = base64.b64encode(res["image_bytes"]).decode("utf-8")
        data_url = f"data:{mime};base64,{b64_out}"

        return {
            "success": True,
            "original_sha256": res["original_sha256"],
            "redacted_sha256": res["redacted_sha256"],
            "image_size": res["image_size"],
            "detections": res["detections"],
            "redaction_parameters": res["redaction_parameters"],
            "telemetry": res["telemetry"],
            "redacted_image_data_url": data_url,
            "redacted_image_base64": b64_out
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Redaction processing error: {str(e)}")


@app.post("/api/v1/redact/json", summary="Redact Image (JSON Body)", tags=["Redaction"])
def redact_image_json(req: RedactJsonRequest):
    """
    JSON endpoint for websites submitting base64 or image URLs in application/json format.
    """
    raw_bytes: bytes = b""

    if req.image_url:
        try:
            import requests
            headers = {"User-Agent": "Mozilla/5.0 PrivacyRedactionEngine/2.0"}
            r = requests.get(req.image_url, headers=headers, timeout=20)
            if r.status_code != 200:
                raise HTTPException(status_code=400, detail=f"Failed to fetch image from URL: HTTP {r.status_code}")
            raw_bytes = r.content
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Failed to download image from URL: {str(e)}")
    elif req.image_base64:
        try:
            clean_b64 = req.image_base64.split(",", 1)[1] if "," in req.image_base64 else req.image_base64
            raw_bytes = base64.b64decode(clean_b64)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Invalid base64 payload: {str(e)}")
    else:
        raise HTTPException(status_code=400, detail="Must provide either image_url or image_base64 in JSON body")

    try:
        res = redaction_engine.redact(
            raw_bytes,
            redact_faces=req.redact_faces,
            redact_plates=req.redact_plates,
            blur_radius=req.blur_radius,
            expand_margin_pct=req.expand_margin_pct,
            feather=req.feather,
            strip_exif=req.strip_exif,
            use_cache=req.use_cache,
            output_format=req.output_format
        )

        fmt = req.output_format.lower()
        mime = f"image/{fmt}"
        b64_out = base64.b64encode(res["image_bytes"]).decode("utf-8")
        data_url = f"data:{mime};base64,{b64_out}"

        return {
            "success": True,
            "original_sha256": res["original_sha256"],
            "redacted_sha256": res["redacted_sha256"],
            "image_size": res["image_size"],
            "detections": res["detections"],
            "redaction_parameters": res["redaction_parameters"],
            "telemetry": res["telemetry"],
            "redacted_image_data_url": data_url,
            "redacted_image_base64": b64_out
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Redaction processing error: {str(e)}")


@app.post("/api/v1/detect", summary="Detect PII Targets Only (No Redaction)", tags=["Detection"])
def detect_only(req: DetectJsonRequest):
    """
    Returns detected face and vehicle license plate bounding boxes and metadata
    WITHOUT modifying image pixels. Useful for websites wishing to draw client-side
    canvases, bounding boxes, or conduct manual audits.
    """
    raw_bytes: bytes = b""

    if req.image_url:
        try:
            import requests
            headers = {"User-Agent": "Mozilla/5.0 PrivacyRedactionEngine/2.0"}
            r = requests.get(req.image_url, headers=headers, timeout=20)
            if r.status_code != 200:
                raise HTTPException(status_code=400, detail=f"Failed to fetch image from URL: HTTP {r.status_code}")
            raw_bytes = r.content
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Failed to download image from URL: {str(e)}")
    elif req.image_base64:
        try:
            clean_b64 = req.image_base64.split(",", 1)[1] if "," in req.image_base64 else req.image_base64
            raw_bytes = base64.b64decode(clean_b64)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Invalid base64 payload: {str(e)}")
    else:
        raise HTTPException(status_code=400, detail="Must provide either image_url or image_base64")

    try:
        faces, plates, cache_hit, latency_ms = redaction_engine.detect_all(raw_bytes, use_cache=req.use_cache)
        return {
            "success": True,
            "detections": {
                "faces_count": len(faces),
                "plates_count": len(plates),
                "faces": faces,
                "plates": plates
            },
            "telemetry": {
                "detection_latency_ms": latency_ms,
                "cache_hit": cache_hit
            }
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Detection error: {str(e)}")


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8002))
    host = os.getenv("HOST", "0.0.0.0")
    uvicorn.run("main:app", host=host, port=port, reload=True)
