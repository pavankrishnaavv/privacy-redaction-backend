# Privacy Redaction Backend Engine
### Automated Face & Vehicle License Plate De-Identification Microservice
**Powered by Plate Recognizer Snapshot API + Face++ Detection API + Adaptive Gaussian Filter**

[![Python 3.9+](https://img.shields.io/badge/Python-3.9%2B-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-Framework-009688.svg)](https://fastapi.tiangolo.com/)
[![Plate Recognizer API](https://img.shields.io/badge/Plate%20Recognizer-Snapshot%20API-orange.svg)](https://platerecognizer.com/)
[![Face++ API](https://img.shields.io/badge/Face%2B%2B-Detect%20API-blueviolet.svg)](https://www.faceplusplus.com/)
[![Docker](https://img.shields.io/badge/Docker-Ready-2496ED.svg)](https://www.docker.com/)

---

## 1. Overview & Zero-Config Portability

The **Privacy Redaction Backend Engine** is a high-throughput, headless REST API service and CLI engine designed for websites and applications to automatically identify and blur human faces and vehicle license plates.

> **Zero-Configuration Ready:**
> The API keys and secrets for **Plate Recognizer** and **Face++** are pre-configured in `.env`, `docker-compose.yml`, and baked into the engine codebase defaults. Anyone who clones this repository can immediately run and use the engine without registering or setting up their own API keys!

### Key Features
- **Biometric Face Redaction (Face++):** Detects human faces, biometric boundaries, and demographic metadata (age, gender).
- **Vehicle License Plate Redaction (Plate Recognizer):** Detects vehicle registration plates, OCR text, and vehicle classifications (Sedan, SUV, Truck, etc.) with >99% confidence.
- **Adaptive Gaussian Blur:** Blur radius dynamically scales to target dimensions (+12% safety margin to prevent hair, chin, or plate border leaks) with anti-aliased feathering.
- **100% EXIF Purge:** Strips camera serial numbers, device metadata, and pinpoint GPS coordinates via clean pixel re-rasterization.
- **SQLite SHA-256 Cache:** Automatically hashes images to prevent duplicate queries, delivering cached redactions in `< 1ms` and preserving API quotas.
- **Headless & Cross-Platform:** Designed to be called by any frontend (React, Vue, Next.js, HTML) or backend (Node.js, Python, PHP, Go).

---

## 2. Quick Start (Clone & Run in 30 Seconds)

### Option A: Direct Python Server

```bash
# 1. Clone the repository
git clone https://github.com/pavankrishnaavv/privacy-redaction-backend.git
cd privacy-redaction-backend

# 2. Install dependencies
pip install -r requirements.txt

# 3. Start the server (All API keys are pre-loaded!)
python main.py
```

*Server is live at: `http://localhost:8002`*  
*Interactive Swagger UI Documentation: `http://localhost:8002/docs`*

---

### Option B: Docker Compose (1-Command Deployment)

```bash
docker compose up -d
```
*The containerized service automatically builds and runs on port `8002`.*

---

## 3. REST API Reference

Interactive OpenAPI / Swagger docs are auto-generated at **`/docs`** (and ReDoc at **`/redoc`**).

| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `POST` | `/api/v1/redact` | Redact image (multipart file upload, image URL, or base64) |
| `POST` | `/api/v1/redact/json` | Redact image using pure JSON request body |
| `POST` | `/api/v1/detect` | Bounding-box detection only (does not modify pixels) |
| `GET` | `/api/v1/health` | Health check & API credential diagnostics |
| `GET` | `/api/v1/metrics` | Operational throughput, cache hit rate, and latency metrics |
| `POST` | `/api/v1/cache/clear` | Clear the SQLite SHA-256 detection cache |

---

### `POST /api/v1/redact` Parameters

| Parameter | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `file` | `UploadFile` | `None` | Image file binary upload (`multipart/form-data`) |
| `image_url` | `string` | `None` | Public HTTP/HTTPS URL of the image |
| `image_base64` | `string` | `None` | Base64-encoded image string or data URL |
| `blur_radius` | `int` | `None` | Gaussian blur kernel radius (default: adaptive 35%) |
| `expand_margin_pct`| `float` | `0.12` | Boundary safety padding (12%) |
| `redact_faces` | `bool` | `true` | Redact human faces via Face++ |
| `redact_plates` | `bool` | `true` | Redact vehicle license plates via Plate Recognizer |
| `feather` | `bool` | `true` | Apply anti-aliased feathered mask edge |
| `strip_exif` | `bool` | `true` | Purge 100% of camera/GPS EXIF metadata |
| `response_type` | `string` | `"json"` | `"json"` (metadata + base64) or `"binary"` (raw `image/png`) |

---

## 4. How External Websites Call This Backend

### A. Vanilla JavaScript / HTML (Browser Fetch)

```html
<input type="file" id="uploadInput" accept="image/*" />
<img id="redactedResult" alt="Redacted Output" style="max-width: 600px;" />

<script>
document.getElementById('uploadInput').addEventListener('change', async (e) => {
  const file = e.target.files[0];
  if (!file) return;

  const form = new FormData();
  form.append('file', file);
  form.append('blur_radius', '25'); // optional: 10-60 px
  form.append('response_type', 'json');

  const response = await fetch('http://localhost:8002/api/v1/redact', {
    method: 'POST',
    body: form
  });

  const data = await response.json();
  if (data.success) {
    document.getElementById('redactedResult').src = data.redacted_image_data_url;
    console.log(`Faces blurred: ${data.detections.faces_count}, Plates blurred: ${data.detections.plates_count}`);
  }
});
</script>
```

### B. Direct Binary Image Streaming (`response_type=binary`)

```javascript
const form = new FormData();
form.append('file', file);
form.append('response_type', 'binary'); // Streams back raw image/png!

const response = await fetch('http://localhost:8002/api/v1/redact', {
  method: 'POST',
  body: form
});

const blob = await response.blob();
const imageUrl = URL.createObjectURL(blob);
// Directly use in <img src={imageUrl} />
```

### C. Node.js (Backend Upload / S3 Pipeline)

```javascript
const axios = require('axios');
const FormData = require('form-data');
const fs = require('fs');

async function redactImage(inputPath, outputPath) {
  const form = new FormData();
  form.append('file', fs.createReadStream(inputPath));
  form.append('response_type', 'binary');

  const res = await axios.post('http://localhost:8002/api/v1/redact', form, {
    headers: form.getHeaders(),
    responseType: 'arraybuffer'
  });

  fs.writeFileSync(outputPath, res.data);
}
```

### D. Python Client

```python
import requests

with open("sample.jpg", "rb") as f:
    r = requests.post(
        "http://localhost:8002/api/v1/redact",
        files={"file": f},
        data={"blur_radius": 25, "response_type": "json"}
    )

data = r.json()
print("Faces found:", data["detections"]["faces_count"])
print("Plates found:", data["detections"]["plates_count"])
```

### E. cURL

```bash
# Save binary redacted PNG directly
curl -X POST "http://localhost:8002/api/v1/redact" \
  -F "file=@incident.jpg" \
  -F "response_type=binary" \
  --output incident_redacted.png
```

---

## 5. Command-Line Interface (CLI)

The CLI is included in `cli.py`:

```bash
# Redact a single image
python cli.py path/to/image.jpg -o output_redacted.png -r 25

# Redact only plates
python cli.py path/to/image.jpg --plates-only

# Redact only faces
python cli.py path/to/image.jpg --faces-only

# Batch redact an entire directory
python cli.py --batch ./raw_photos --output-dir ./safe_photos

# Check API credentials and cache status
python cli.py --check-keys

# Output structured JSON telemetry
python cli.py path/to/image.jpg --json
```

---

## 6. Verification Benchmarks on Real-World Specimens

Run the automated test benchmark:
```bash
python tests/test_user_images.py
```

| Specimen | Type | Resolution | Detections | Pipeline Latency | Redaction Result |
| :--- | :--- | :---: | :--- | :---: | :--- |
| `street_rain_motorcycle.jpg` | Busy Delhi rain street | `1024 x 558` | **3 Faces** (Driver + 2 Bystanders)<br>**1 Plate** (`DL14SV7890`, 99.5% conf) | `2206 ms` | **100% Redacted** |
| `portrait_glasses.jpg` | Indoor selfie portrait | `960 x 720` | **1 Face** (Male, ~19 yrs) | `1976 ms` | **100% Redacted** |
| `night_highway_temple.jpg` | Night highway scene | `1024 x 768` | `0 Faces` (Backs turned)<br>`0 Plates` (Occluded/shadowed) | `2107 ms` | **Clean Baseline (0 false positives)** |

---

## 7. Configuration Reference

```ini
# Plate Recognizer API Credentials (https://guides.platerecognizer.com)
PLATE_RECOGNIZER_TOKEN=efabb54d2f9443ee3efb020860584e07bb2e479c
PLATE_RECOGNIZER_ENDPOINT=https://api.platerecognizer.com/v1/plate-reader/

# Face++ Detection API Credentials (https://console.faceplusplus.com)
FACEPLUSPLUS_API_KEY=I9J_x0mJmi9w3D_crZmkpKXJs6pvuQbE
FACEPLUSPLUS_API_SECRET=AXfXcLBzVa0FB0YdniFg5sIvQuGkaRmk
FACEPLUSPLUS_ENDPOINT=https://api-us.faceplusplus.com/facepp/v3/detect

# Redaction Parameters
DEFAULT_BLUR_RADIUS=25
EXPAND_MARGIN_PERCENT=0.12
FEATHER_EDGES=true
STRIP_EXIF=true

# Server Configuration
PORT=8002
HOST=0.0.0.0
CORS_ORIGINS=*
```

---

## 8. License

Distributed under the MIT License.
