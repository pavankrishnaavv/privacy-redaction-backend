#!/usr/bin/env python3
"""
Privacy Redaction Engine — Command Line Interface (CLI)
=======================================================
Redact faces and vehicle license plates using Plate Recognizer API and Face++ API
with high-density Gaussian blur, adaptive boundary scaling, and EXIF purge.
"""

import os
import sys
import json
import time
import argparse
from typing import List

# Ensure package on path
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from engine.redaction_engine import redaction_engine


def print_banner():
    print("=" * 76)
    print("  PRIVACY REDACTION ENGINE — MULTIMODAL PII OBLITERATION")
    print("  Face++ (Biometric Faces) + Plate Recognizer (Vehicle Plates) + Gaussian Blur")
    print("=" * 76)


def print_stats_table(res: dict):
    print("\n" + "-" * 76)
    print(f"  ORIGINAL SHA-256: {res['original_sha256']}")
    print(f"  REDACTED SHA-256: {res['redacted_sha256']}")
    print(f"  RESOLUTION:       {res['image_size']['width']} x {res['image_size']['height']} px")
    print(f"  OUTPUT FILE:      {res.get('output_path', 'N/A')}")
    print("-" * 76)

    det = res["detections"]
    print(f"\n[1] PII DETECTIONS FOUND: {det['faces_count']} Face(s) | {det['plates_count']} License Plate(s)")

    if det["faces"]:
        print("\n  • FACES DETECTED (Face++):")
        for i, face in enumerate(det["faces"], 1):
            box = face["box"]
            gender = face.get("gender", "N/A")
            age = face.get("age", "N/A")
            print(f"    [{i}] Coords: [{box['xmin']}, {box['ymin']}, {box['xmax']}, {box['ymax']}] "
                  f"(WxH: {box['xmax'] - box['xmin']}x{box['ymax'] - box['ymin']}px) | Est: {gender}, ~{age} yrs")

    if det["plates"]:
        print("\n  • LICENSE PLATES DETECTED (Plate Recognizer):")
        for i, plate in enumerate(det["plates"], 1):
            box = plate["box"]
            num = plate.get("plate_text", "UNKNOWN")
            conf = plate.get("confidence", 0.0) * 100
            veh = plate.get("vehicle_type", "Vehicle")
            print(f"    [{i}] Plate: '{num}' ({conf:.1f}% conf) | Vehicle: {veh} | "
                  f"Coords: [{box['xmin']}, {box['ymin']}, {box['xmax']}, {box['ymax']}]")

    print("\n[2] REDACTION PARAMETERS APPLIED:")
    rp = res["redaction_parameters"]
    print(f"  • Gaussian Blur Radius: {rp['blur_radius_applied']}")
    print(f"  • Safety Boundary Pad:  {rp['margin_expanded_pct'] * 100:.1f}%")
    print(f"  • Feathered Edges:      {'Enabled' if rp['feather_edges'] else 'Disabled'}")
    print(f"  • EXIF / GPS Metadata:  {'100% Purged (0 bytes leaked)' if rp['exif_purged'] else 'Preserved'}")
    print(f"  • Format:               {rp['output_format']}")

    print("\n[3] PERFORMANCE & CACHE TELEMETRY:")
    tel = res["telemetry"]
    print(f"  • Detection Latency:    {tel['detection_latency_ms']:.2f} ms")
    print(f"  • Gaussian Blur Filter: {tel['blur_latency_ms']:.2f} ms")
    print(f"  • Total Pipeline Time:  {tel['total_pipeline_ms']:.2f} ms")
    print(f"  • SQLite Cache Hit:     {'YES (Quota Preserved)' if tel['cache_hit'] else 'NO (Live API Queried)'}")
    print("-" * 76)


def main():
    parser = argparse.ArgumentParser(
        description="Privacy Redaction Engine — Gaussian Blur PII Redaction CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )

    parser.add_argument("input", nargs="?", help="Path to input image file (JPG, PNG, WEBP)")
    parser.add_argument("-o", "--output", help="Path to save redacted image (defaults to <name>_redacted.<ext>)")
    parser.add_argument("-r", "--radius", type=int, default=None, help="Gaussian blur radius (e.g. 15-50). Default: adaptive 35%%")
    parser.add_argument("-m", "--margin", type=float, default=None, help="Safety margin expansion fraction (e.g. 0.12). Default: 0.12")
    parser.add_argument("--faces-only", action="store_true", help="Redact faces only (skip license plates)")
    parser.add_argument("--plates-only", action="store_true", help="Redact license plates only (skip faces)")
    parser.add_argument("--no-feather", action="store_true", help="Use sharp rectangular boundary instead of feathered edges")
    parser.add_argument("--no-cache", action="store_true", help="Bypass SQLite SHA-256 detection cache and force live API query")
    parser.add_argument("--keep-exif", action="store_true", help="Keep original EXIF metadata (not recommended for privacy)")
    parser.add_argument("--batch", help="Path to directory for batch processing all images")
    parser.add_argument("--output-dir", help="Output directory for batch processing")
    parser.add_argument("--check-keys", action="store_true", help="Validate Plate Recognizer & Face++ API credentials")
    parser.add_argument("--stats", action="store_true", help="Print overall operational stats and cache diagnostics")
    parser.add_argument("--json", action="store_true", help="Output results in JSON format")

    args = parser.parse_args()

    if args.check_keys or args.stats:
        metrics = redaction_engine.get_metrics()
        if args.json:
            print(json.dumps(metrics, indent=2))
        else:
            print_banner()
            print(f"Engine Status:          {metrics['engine_status']}")
            print(f"Plate Recognizer Token: {'CONFIGURED' if metrics['credentials_configured']['plate_recognizer'] else 'MISSING'}")
            print(f"Face++ API Key & Sec:   {'CONFIGURED' if metrics['credentials_configured']['faceplusplus'] else 'MISSING'}")
            print(f"Cached Images:          {metrics['cache']['cached_items']} entries ({metrics['cache']['db_path']})")
            print(f"Total Processed:        {metrics['stats']['total_images_processed']}")
            print(f"Total Faces Redacted:   {metrics['stats']['total_faces_redacted']}")
            print(f"Total Plates Redacted:  {metrics['stats']['total_plates_redacted']}")
            print(f"Cache Hits:             {metrics['stats']['cache_hits']}")
        return

    # Batch mode
    if args.batch:
        if not os.path.isdir(args.batch):
            print(f"[ERROR] Directory not found: {args.batch}")
            sys.exit(1)

        out_dir = args.output_dir or os.path.join(args.batch, "redacted")
        os.makedirs(out_dir, exist_ok=True)

        valid_exts = (".jpg", ".jpeg", ".png", ".webp", ".bmp")
        files = [f for f in os.listdir(args.batch) if f.lower().endswith(valid_exts) and not f.endswith("_redacted.png")]

        if not files:
            print(f"[WARN] No image files found in {args.batch}")
            return

        print_banner()
        print(f"Processing batch of {len(files)} image(s)... Output directory: {out_dir}")

        for i, fname in enumerate(files, 1):
            in_path = os.path.join(args.batch, fname)
            out_path = os.path.join(out_dir, f"redacted_{fname}")
            try:
                res = redaction_engine.redact_file(
                    in_path,
                    output_path=out_path,
                    redact_faces=not args.plates_only,
                    redact_plates=not args.faces_only,
                    blur_radius=args.radius,
                    expand_margin_pct=args.margin,
                    feather=not args.no_feather,
                    strip_exif=not args.keep_exif,
                    use_cache=not args.no_cache
                )
                faces = res["detections"]["faces_count"]
                plates = res["detections"]["plates_count"]
                hit = "HIT" if res["telemetry"]["cache_hit"] else "LIVE"
                print(f"  [{i}/{len(files)}] {fname} -> {faces} faces, {plates} plates ({hit}, {res['telemetry']['total_pipeline_ms']:.1f}ms)")
            except Exception as e:
                print(f"  [{i}/{len(files)}] {fname} -> FAILED: {str(e)}")

        print("\n[SUCCESS] Batch redaction complete.")
        return

    # Single file mode
    if not args.input:
        parser.print_help()
        sys.exit(1)

    if not os.path.isfile(args.input):
        print(f"[ERROR] Input file not found: {args.input}")
        sys.exit(1)

    try:
        res = redaction_engine.redact_file(
            args.input,
            output_path=args.output,
            redact_faces=not args.plates_only,
            redact_plates=not args.faces_only,
            blur_radius=args.radius,
            expand_margin_pct=args.margin,
            feather=not args.no_feather,
            strip_exif=not args.keep_exif,
            use_cache=not args.no_cache
        )

        if args.json:
            # Exclude raw image bytes from JSON dump
            res_clean = {k: v for k, v in res.items() if k not in ("image_pil", "image_bytes")}
            print(json.dumps(res_clean, indent=2))
        else:
            print_banner()
            print_stats_table(res)

    except Exception as e:
        print(f"[ERROR] Redaction failed: {str(e)}")
        sys.exit(1)


if __name__ == "__main__":
    main()
