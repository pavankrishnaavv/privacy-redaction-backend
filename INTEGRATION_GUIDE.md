# Website Integration Guide
## How to Integrate the Privacy Redaction Backend into Any Website

This backend provides a standalone, high-performance REST API to identify human faces and vehicle license plates, redacting them using Gaussian blur. External websites and web applications can call this service using standard HTTP requests.

---

## 1. Quick Start: Running the Backend

### Option A: Run with Python
```bash
cd privacy-redaction-backend
python -m pip install -r requirements.txt
python main.py
```
*The service starts on `http://localhost:8002`.*
*Interactive OpenAPI documentation is live at `http://localhost:8002/docs`.*

### Option B: Run with Docker (1-command)
```bash
cd privacy-redaction-backend
docker compose up -d
```

---

## 2. API Endpoints for Websites

| Endpoint | Method | Input | Output | Use Case |
| :--- | :--- | :--- | :--- | :--- |
| `/api/v1/redact` | `POST` | `multipart/form-data` or URL | JSON or Raw Image (`image/png`) | Main redaction endpoint for user uploads |
| `/api/v1/redact/json` | `POST` | `application/json` | JSON with Base64 & metadata | For web SPAs sending Base64 or image URLs |
| `/api/v1/detect` | `POST` | `application/json` | JSON (bounding boxes only) | For websites drawing custom canvas overlays |
| `/api/v1/health` | `GET` | None | JSON | Health check / uptime monitoring |
| `/api/v1/metrics` | `GET` | None | JSON | Performance & usage telemetry |

---

## 3. Website Code Examples

### A. Vanilla JavaScript / HTML (Browser Fetch)

Add this script to any website with an `<input type="file">` to automatically redact images when selected:

```html
<input type="file" id="imageInput" accept="image/*" />
<img id="redactedPreview" alt="Redacted Output" style="max-width: 500px;" />

<script>
document.getElementById('imageInput').addEventListener('change', async (e) => {
  const file = e.target.files[0];
  if (!file) return;

  const formData = new FormData();
  formData.append('file', file);
  formData.append('blur_radius', '25');       // Optional: blur radius (10-60)
  formData.append('expand_margin_pct', '0.12'); // Optional: 12% boundary padding
  formData.append('response_type', 'json');    // 'json' or 'binary'

  try {
    const response = await fetch('http://localhost:8002/api/v1/redact', {
      method: 'POST',
      body: formData,
    });

    const data = await response.json();
    if (data.success) {
      // Display the redacted image on your website
      document.getElementById('redactedPreview').src = data.redacted_image_data_url;
      
      console.log(`Faces blurred: ${data.detections.faces_count}`);
      console.log(`Plates blurred: ${data.detections.plates_count}`);
    }
  } catch (error) {
    console.error('Redaction failed:', error);
  }
});
</script>
```

---

### B. Direct Image Embedding (`response_type=binary`)

You can directly fetch the raw binary image stream (`image/png` or `image/jpeg`):

```javascript
async function getRedactedImageBlob(file) {
  const formData = new FormData();
  formData.append('file', file);
  formData.append('response_type', 'binary'); // Streams back binary image!

  const response = await fetch('http://localhost:8002/api/v1/redact', {
    method: 'POST',
    body: formData,
  });

  const blob = await response.blob();
  const imageUrl = URL.createObjectURL(blob);
  
  // Use in an <img> tag or trigger download
  return imageUrl;
}
```

---

### C. React / Next.js Component Example

```tsx
import React, { useState } from 'react';

export const PrivacyRedactor: React.FC = () => {
  const [redactedUrl, setRedactedUrl] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const handleUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    setLoading(true);
    const form = new FormData();
    form.append('file', file);
    form.append('blur_radius', '25');

    try {
      const res = await fetch('http://localhost:8002/api/v1/redact', {
        method: 'POST',
        body: form,
      });
      const data = await res.json();
      setRedactedUrl(data.redacted_image_data_url);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div>
      <input type="file" onChange={handleUpload} accept="image/*" />
      {loading && <p>Obfuscating biometric faces & vehicle plates...</p>}
      {redactedUrl && <img src={redactedUrl} alt="Redacted" />}
    </div>
  );
};
```

---

### D. Node.js (Backend Proxy / Upload Pipeline)

If your website server wants to redact images before saving them to Amazon S3 or Google Cloud Storage:

```javascript
const axios = require('axios');
const FormData = require('form-data');
const fs = require('fs');

async function redactAndSave(inputFilePath, outputFilePath) {
  const form = new FormData();
  form.append('file', fs.createReadStream(inputFilePath));
  form.append('response_type', 'binary');

  const response = await axios.post('http://localhost:8002/api/v1/redact', form, {
    headers: form.getHeaders(),
    responseType: 'arraybuffer'
  });

  fs.writeFileSync(outputFilePath, response.data);
  console.log(`Saved redacted image to ${outputFilePath}`);
}
```

---

### E. Python (Requests)

```python
import requests

with open("user_upload.jpg", "rb") as f:
    response = requests.post(
        "http://localhost:8002/api/v1/redact",
        files={"file": f},
        data={"blur_radius": 25, "response_type": "json"}
    )

data = response.json()
print("Faces found:", data["detections"]["faces_count"])
print("Plates found:", data["detections"]["plates_count"])
```

---

### F. cURL (Terminal / Bash)

```bash
# Get JSON with Base64 & Detection Coordinates
curl -X POST "http://localhost:8002/api/v1/redact" \
  -F "file=@incident.jpg" \
  -F "blur_radius=25"

# Save binary redacted file directly
curl -X POST "http://localhost:8002/api/v1/redact" \
  -F "file=@incident.jpg" \
  -F "response_type=binary" \
  --output incident_redacted.png
```

---

## 4. Redaction Parameters Reference

| Parameter | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `blur_radius` | `int` | `null` (adaptive) | Radius of Gaussian kernel in pixels. If omitted, dynamically scales to 35% of target box. |
| `expand_margin_pct` | `float` | `0.12` (12%) | Safety margin padding so hair, chin, or plate edges do not leak. |
| `redact_faces` | `bool` | `true` | Whether to redact human faces via Face++. |
| `redact_plates` | `bool` | `true` | Whether to redact vehicle license plates via Plate Recognizer. |
| `feather` | `bool` | `true` | Smooth anti-aliased edge gradient on blurred region. |
| `strip_exif` | `bool` | `true` | Strips 100% of camera serial numbers, date/time, and GPS coordinates. |
| `use_cache` | `bool` | `true` | Caches detection results by SHA-256 hash to preserve API quotas. |
| `response_type` | `string` | `"json"` | `"json"` returns metadata + base64; `"binary"` returns raw `image/png` stream. |
| `output_format` | `string` | `"PNG"` | Output image format: `PNG`, `JPEG`, or `WEBP`. |
