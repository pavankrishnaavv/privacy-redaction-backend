"""
Privacy Redaction Engine
------------------------
Core multimodal privacy engine combining:
1. Plate Recognizer API: Identifies vehicle license plates and vehicle types.
2. Face++ Detect API: Identifies human faces, coordinates, and facial attributes.
3. Gaussian Blur Pipeline: Obliterates PII visual features with adaptive radius,
   safety boundary padding, and optional edge-feathering.
4. EXIF Purge: Strips 100% of embedded GPS coordinates and device metadata.
5. SHA-256 Quota Cache: SQLite-backed caching to prevent redundant API queries.
"""

import os
import io
import time
import json
import hashlib
import logging
import concurrent.futures
from typing import Dict, Any, List, Optional, Tuple, Union

import requests
from PIL import Image, ImageFilter, ImageDraw
from dotenv import load_dotenv

from .cache import redaction_cache

load_dotenv()
logger = logging.getLogger("redaction_engine")
logging.basicConfig(level=logging.INFO)

# Default credentials provided by user
DEFAULT_PLATE_TOKEN = "efabb54d2f9443ee3efb020860584e07bb2e479c"
DEFAULT_PLATE_ENDPOINT = "https://api.platerecognizer.com/v1/plate-reader/"

DEFAULT_FACE_KEY = "I9J_x0mJmi9w3D_crZmkpKXJs6pvuQbE"
DEFAULT_FACE_SECRET = "AXfXcLBzVa0FB0YdniFg5sIvQuGkaRmk"
DEFAULT_FACE_ENDPOINT = "https://api-us.faceplusplus.com/facepp/v3/detect"


class RedactionEngine:
    """
    Enterprise-grade Face & License Plate Redaction Engine.
    Processes images and applies irreversible Gaussian blur over detected PII regions.
    """

    def __init__(
        self,
        plate_token: Optional[str] = None,
        plate_endpoint: Optional[str] = None,
        face_key: Optional[str] = None,
        face_secret: Optional[str] = None,
        face_endpoint: Optional[str] = None,
        default_blur_radius: int = 25,
        default_margin_pct: float = 0.12,
        feather_edges: bool = True
    ):
        self.plate_token = plate_token or os.getenv("PLATE_RECOGNIZER_TOKEN", DEFAULT_PLATE_TOKEN)
        self.plate_endpoint = plate_endpoint or os.getenv("PLATE_RECOGNIZER_ENDPOINT", DEFAULT_PLATE_ENDPOINT)

        self.face_key = face_key or os.getenv("FACEPLUSPLUS_API_KEY", DEFAULT_FACE_KEY)
        self.face_secret = face_secret or os.getenv("FACEPLUSPLUS_API_SECRET", DEFAULT_FACE_SECRET)
        self.face_endpoint = face_endpoint or os.getenv("FACEPLUSPLUS_ENDPOINT", DEFAULT_FACE_ENDPOINT)

        self.default_blur_radius = int(os.getenv("DEFAULT_BLUR_RADIUS", default_blur_radius))
        self.default_margin_pct = float(os.getenv("EXPAND_MARGIN_PERCENT", default_margin_pct))
        self.feather_edges = os.getenv("FEATHER_EDGES", str(feather_edges)).lower() in ("true", "1", "yes")

        # Telemetry metrics
        self.stats = {
            "total_images_processed": 0,
            "total_faces_redacted": 0,
            "total_plates_redacted": 0,
            "total_api_calls_facepp": 0,
            "total_api_calls_plate": 0,
            "cache_hits": 0,
            "errors_handled": 0
        }

    # -------------------------------------------------------------------------
    # Detection: Plate Recognizer API
    # -------------------------------------------------------------------------
    def detect_plates(self, image_bytes: bytes, timeout: int = 25) -> List[Dict[str, Any]]:
        """
        Query Plate Recognizer Snapshot API to locate license plates.
        Returns standardized bounding boxes and OCR details.
        """
        if not self.plate_token:
            logger.warning("Plate Recognizer token not configured.")
            return []

        headers = {"Authorization": f"Token {self.plate_token}"}
        files = {"upload": ("vehicle_sample.jpg", image_bytes, "image/jpeg")}

        self.stats["total_api_calls_plate"] += 1
        try:
            resp = requests.post(self.plate_endpoint, files=files, headers=headers, timeout=timeout)
            if resp.status_code not in (200, 201):
                logger.error(f"Plate Recognizer error HTTP {resp.status_code}: {resp.text[:200]}")
                return []

            data = resp.json()
            plates = []
            for item in data.get("results", []):
                box = item.get("box", {})
                vehicle = item.get("vehicle", {})
                plates.append({
                    "type": "license_plate",
                    "plate_text": item.get("plate", "").upper(),
                    "confidence": round(float(item.get("score", 0.0)), 4),
                    "vehicle_type": vehicle.get("type", "Unknown"),
                    "vehicle_confidence": round(float(vehicle.get("score", 0.0)), 4) if vehicle else None,
                    "box": {
                        "xmin": int(box.get("xmin", 0)),
                        "ymin": int(box.get("ymin", 0)),
                        "xmax": int(box.get("xmax", 0)),
                        "ymax": int(box.get("ymax", 0))
                    }
                })
            return plates

        except Exception as e:
            self.stats["errors_handled"] += 1
            logger.error(f"Plate Recognizer exception: {str(e)}")
            return []

    # -------------------------------------------------------------------------
    # Detection: Face++ API
    # -------------------------------------------------------------------------
    def detect_faces(self, image_bytes: bytes, timeout: int = 25) -> List[Dict[str, Any]]:
        """
        Query Face++ Detection API to locate human faces.
        Returns standardized bounding boxes and demographic attributes.
        """
        if not self.face_key or not self.face_secret:
            logger.warning("Face++ credentials not configured.")
            return []

        payload = {
            "api_key": self.face_key,
            "api_secret": self.face_secret,
            "return_attributes": "gender,age,headpose"
        }
        files = {"image_file": ("face_sample.jpg", image_bytes, "image/jpeg")}

        self.stats["total_api_calls_facepp"] += 1
        try:
            resp = requests.post(self.face_endpoint, data=payload, files=files, timeout=timeout)
            if resp.status_code != 200:
                logger.error(f"Face++ error HTTP {resp.status_code}: {resp.text[:200]}")
                return []

            data = resp.json()
            faces = []
            for face in data.get("faces", []):
                rect = face.get("face_rectangle", {})
                left = int(rect.get("left", 0))
                top = int(rect.get("top", 0))
                width = int(rect.get("width", 0))
                height = int(rect.get("height", 0))
                attrs = face.get("attributes", {})

                faces.append({
                    "type": "face",
                    "face_token": face.get("face_token"),
                    "gender": attrs.get("gender", {}).get("value"),
                    "age": attrs.get("age", {}).get("value"),
                    "box": {
                        "xmin": left,
                        "ymin": top,
                        "xmax": left + width,
                        "ymax": top + height
                    }
                })
            return faces

        except Exception as e:
            self.stats["errors_handled"] += 1
            logger.error(f"Face++ exception: {str(e)}")
            return []

    # -------------------------------------------------------------------------
    # Concurrent Multi-Detector with Cache
    # -------------------------------------------------------------------------
    def detect_all(
        self,
        image_bytes: bytes,
        use_cache: bool = True
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], bool, float]:
        """
        Execute Face++ and Plate Recognizer detection in parallel.
        Uses SHA-256 image hashing to avoid duplicate queries.
        Returns (faces, plates, cache_hit, detection_latency_ms).
        """
        img_hash = hashlib.sha256(image_bytes).hexdigest()
        start_t = time.perf_counter()

        if use_cache:
            cached = redaction_cache.get(img_hash)
            if cached is not None:
                self.stats["cache_hits"] += 1
                latency = round((time.perf_counter() - start_t) * 1000, 2)
                return cached["faces"], cached["plates"], True, latency

        # Inspect dimensions
        try:
            with Image.open(io.BytesIO(image_bytes)) as pil_img:
                width, height = pil_img.size
        except Exception:
            width, height = 0, 0

        # Execute concurrent network requests
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            fut_faces = executor.submit(self.detect_faces, image_bytes)
            fut_plates = executor.submit(self.detect_plates, image_bytes)

            faces = fut_faces.result()
            plates = fut_plates.result()

        latency = round((time.perf_counter() - start_t) * 1000, 2)

        # Store in SQLite cache
        if use_cache and width > 0:
            redaction_cache.set(img_hash, faces, plates, width, height)

        return faces, plates, False, latency

    # -------------------------------------------------------------------------
    # Gaussian Blur Redaction Core
    # -------------------------------------------------------------------------
    def apply_gaussian_blur(
        self,
        pil_image: Image.Image,
        boxes: List[Dict[str, Any]],
        blur_radius: Optional[int] = None,
        expand_margin_pct: Optional[float] = None,
        feather: Optional[bool] = None
    ) -> Image.Image:
        """
        Apply Gaussian blur redaction to all specified bounding boxes.
        - Expands boxes by margin % to ensure no facial or plate edges leak.
        - Scales blur radius proportionally with target size.
        - Feathers mask edges to prevent hard rectangular seams.
        """
        redacted = pil_image.copy()
        img_w, img_h = redacted.size

        margin_pct = self.default_margin_pct if expand_margin_pct is None else expand_margin_pct
        do_feather = self.feather_edges if feather is None else feather

        for item in boxes:
            box = item.get("box", {})
            xmin = box.get("xmin", 0)
            ymin = box.get("ymin", 0)
            xmax = box.get("xmax", 0)
            ymax = box.get("ymax", 0)

            w = xmax - xmin
            h = ymax - ymin
            if w <= 0 or h <= 0:
                continue

            # Expand boundary by safety margin
            pad_x = int(w * margin_pct)
            pad_y = int(h * margin_pct)

            bx0 = max(0, xmin - pad_x)
            by0 = max(0, ymin - pad_y)
            bx1 = min(img_w, xmax + pad_x)
            by1 = min(img_h, ymax + pad_y)

            region_w = bx1 - bx0
            region_h = by1 - by0
            if region_w <= 2 or region_h <= 2:
                continue

            # Compute effective blur radius
            if blur_radius is not None and blur_radius > 0:
                effective_radius = blur_radius
            else:
                # Scale dynamically: at least 15, or 35% of the minor dimension
                effective_radius = max(15, int(min(region_w, region_h) * 0.35))

            # Crop region
            crop_box = (bx0, by0, bx1, by1)
            crop_region = redacted.crop(crop_box)

            # Apply Gaussian Blur (2 passes for complete obfuscation)
            blurred = crop_region.filter(ImageFilter.GaussianBlur(radius=effective_radius))
            blurred = blurred.filter(ImageFilter.GaussianBlur(radius=max(5, effective_radius // 2)))

            if do_feather:
                # Build an elliptical feathered alpha mask
                mask = Image.new("L", (region_w, region_h), 0)
                mask_draw = ImageDraw.Draw(mask)
                # Outer rounded shape
                mask_draw.rounded_rectangle(
                    [1, 1, region_w - 2, region_h - 2],
                    radius=max(6, min(region_w, region_h) // 6),
                    fill=255
                )
                feather_blur = max(3, min(region_w, region_h) // 10)
                mask_blurred = mask.filter(ImageFilter.GaussianBlur(radius=feather_blur))
                redacted.paste(blurred, crop_box, mask=mask_blurred)
            else:
                redacted.paste(blurred, crop_box)

        return redacted

    # -------------------------------------------------------------------------
    # EXIF Purge
    # -------------------------------------------------------------------------
    @staticmethod
    def strip_exif(image: Image.Image) -> Image.Image:
        """Strip 100% of EXIF, GPS, camera serial, and proprietary device tags."""
        clean_img = Image.new(image.mode, image.size)
        clean_img.putdata(list(image.getdata()))
        return clean_img

    # -------------------------------------------------------------------------
    # Main High-Level Redaction Pipeline
    # -------------------------------------------------------------------------
    def redact(
        self,
        image_input: Union[bytes, str, Image.Image],
        redact_faces: bool = True,
        redact_plates: bool = True,
        blur_radius: Optional[int] = None,
        expand_margin_pct: Optional[float] = None,
        feather: Optional[bool] = None,
        strip_exif: bool = True,
        use_cache: bool = True,
        output_format: str = "PNG"
    ) -> Dict[str, Any]:
        """
        Full End-to-End Privacy Redaction Execution:
        1. Ingests bytes, file path, or PIL Image.
        2. Detects faces via Face++ and plates via Plate Recognizer in parallel.
        3. Applies Gaussian blur redaction to targeted regions.
        4. Strips EXIF metadata.
        5. Computes SHA-256 integrity verification hashes.
        6. Returns structured telemetry along with PIL Image and raw bytes.
        """
        start_pipeline = time.perf_counter()

        # Normalize input to PIL Image & raw bytes
        if isinstance(image_input, str):
            if image_input.startswith("http://") or image_input.startswith("https://"):
                headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) PrivacyRedactionEngine/1.0"}
                resp = requests.get(image_input, headers=headers, timeout=20)
                if resp.status_code != 200:
                    raise ValueError(f"Failed to fetch image from URL: HTTP {resp.status_code}")
                raw_bytes = resp.content
            elif os.path.isfile(image_input):
                with open(image_input, "rb") as f:
                    raw_bytes = f.read()
            else:
                raise FileNotFoundError(f"Image file not found: {image_input}")
            pil_original = Image.open(io.BytesIO(raw_bytes)).convert("RGB")
        elif isinstance(image_input, bytes):
            raw_bytes = image_input
            pil_original = Image.open(io.BytesIO(raw_bytes)).convert("RGB")
        elif isinstance(image_input, Image.Image):
            pil_original = image_input.convert("RGB")
            buf = io.BytesIO()
            pil_original.save(buf, format="JPEG", quality=95)
            raw_bytes = buf.getvalue()
        else:
            raise ValueError(f"Unsupported image_input type: {type(image_input)}")

        orig_hash = hashlib.sha256(raw_bytes).hexdigest()
        width, height = pil_original.size

        # 1. Detect
        faces, plates, cache_hit, det_ms = self.detect_all(raw_bytes, use_cache=use_cache)

        # 2. Filter targets
        targets: List[Dict[str, Any]] = []
        if redact_faces:
            targets.extend(faces)
        if redact_plates:
            targets.extend(plates)

        # 3. Apply Gaussian Blur
        blur_t0 = time.perf_counter()
        redacted_pil = self.apply_gaussian_blur(
            pil_original,
            targets,
            blur_radius=blur_radius,
            expand_margin_pct=expand_margin_pct,
            feather=feather
        )
        blur_ms = round((time.perf_counter() - blur_t0) * 1000, 2)

        # 4. Strip EXIF
        if strip_exif:
            redacted_pil = self.strip_exif(redacted_pil)

        # 5. Serialize output bytes
        out_buf = io.BytesIO()
        redacted_pil.save(out_buf, format=output_format.upper())
        redacted_bytes = out_buf.getvalue()
        redacted_hash = hashlib.sha256(redacted_bytes).hexdigest()

        total_ms = round((time.perf_counter() - start_pipeline) * 1000, 2)

        # Update stats
        self.stats["total_images_processed"] += 1
        if redact_faces:
            self.stats["total_faces_redacted"] += len(faces)
        if redact_plates:
            self.stats["total_plates_redacted"] += len(plates)

        return {
            "success": True,
            "original_sha256": orig_hash,
            "redacted_sha256": redacted_hash,
            "image_size": {"width": width, "height": height},
            "detections": {
                "faces_count": len(faces),
                "plates_count": len(plates),
                "faces": faces,
                "plates": plates
            },
            "redaction_parameters": {
                "redacted_faces": redact_faces,
                "redacted_plates": redact_plates,
                "blur_radius_applied": blur_radius if blur_radius is not None else "adaptive (35% scale)",
                "margin_expanded_pct": self.default_margin_pct if expand_margin_pct is None else expand_margin_pct,
                "feather_edges": self.feather_edges if feather is None else feather,
                "exif_purged": strip_exif,
                "output_format": output_format.upper()
            },
            "telemetry": {
                "detection_latency_ms": det_ms,
                "blur_latency_ms": blur_ms,
                "total_pipeline_ms": total_ms,
                "cache_hit": cache_hit
            },
            "image_pil": redacted_pil,
            "image_bytes": redacted_bytes
        }

    # -------------------------------------------------------------------------
    # Helper: Redact File to File
    # -------------------------------------------------------------------------
    def redact_file(
        self,
        input_path: str,
        output_path: Optional[str] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """Convenience method to redact an image file on disk and save the output."""
        if not os.path.isfile(input_path):
            raise FileNotFoundError(f"Input file not found: {input_path}")

        if not output_path:
            base, ext = os.path.splitext(input_path)
            output_path = f"{base}_redacted{ext if ext else '.png'}"

        result = self.redact(input_path, **kwargs)
        with open(output_path, "wb") as f:
            f.write(result["image_bytes"])

        result["output_path"] = output_path
        return result

    def get_metrics(self) -> Dict[str, Any]:
        """Return engine operational metrics and cache diagnostics."""
        cache_diag = redaction_cache.stats()
        return {
            "engine_status": "ONLINE",
            "stats": self.stats,
            "cache": cache_diag,
            "credentials_configured": {
                "plate_recognizer": bool(self.plate_token),
                "faceplusplus": bool(self.face_key and self.face_secret)
            }
        }


# Singleton instance
redaction_engine = RedactionEngine()
