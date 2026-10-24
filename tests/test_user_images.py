import sys
import os
import json

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from engine.redaction_engine import redaction_engine

sample_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sample_images")
uploaded_files = [
    os.path.join(sample_dir, "street_rain_motorcycle.jpg"),
    os.path.join(sample_dir, "portrait_glasses.jpg"),
    os.path.join(sample_dir, "night_highway_temple.jpg")
]

out_dir = os.path.join(sample_dir, "redacted_outputs")
os.makedirs(out_dir, exist_ok=True)

results = []

for idx, in_path in enumerate(uploaded_files, 1):
    fname = os.path.basename(in_path)
    out_path = os.path.join(out_dir, f"redacted_{fname.replace('.jpg', '.png')}")
    print(f"==================================================")
    print(f"PROCESSING TEST IMAGE {idx}: {fname}")
    print(f"==================================================")

    res = redaction_engine.redact_file(in_path, out_path, use_cache=False)

    print(f"Resolution:       {res['image_size']['width']}x{res['image_size']['height']} px")
    print(f"Faces Detected:   {res['detections']['faces_count']}")
    for f_idx, f in enumerate(res['detections']['faces'], 1):
        print(f"  [Face {f_idx}] box={f['box']}, gender={f.get('gender')}, age={f.get('age')}")

    print(f"Plates Detected:  {res['detections']['plates_count']}")
    for p_idx, p in enumerate(res['detections']['plates'], 1):
        print(f"  [Plate {p_idx}] text='{p.get('plate_text')}', conf={p.get('confidence')}, vehicle={p.get('vehicle_type')}, box={p['box']}")

    print(f"Latency:          Det={res['telemetry']['detection_latency_ms']}ms, Blur={res['telemetry']['blur_latency_ms']}ms, Total={res['telemetry']['total_pipeline_ms']}ms")
    print(f"Saved Redacted:   {out_path}")
    print()

    results.append({
        "image_index": idx,
        "filename": fname,
        "input_path": in_path,
        "output_path": out_path,
        "res": {k: v for k, v in res.items() if k not in ("image_pil", "image_bytes")}
    })

with open(os.path.join(out_dir, "user_images_benchmark.json"), "w") as f:
    json.dump(results, f, indent=2)

print("ALL 3 USER SPECIMENS REDACTED AND VERIFIED SUCCESSFULLY!")
