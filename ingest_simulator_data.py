#!/usr/bin/env python3
"""
Ingest synthetic data from simulator into the API.

This script generates synthetic data using the simulator and ingests it
into the running API via the /api/v1/ingest/batch endpoint.
"""

import sys
from pathlib import Path
import yaml
import requests
import pandas as pd
from datetime import datetime, timedelta, date

# Add paths
REPO = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "simulator"))

from simulator.dataset import build_dataset
from simulator.models import SimConfig

BASE_URL = "http://localhost:8000"

print("=" * 70)
print("INGESTING SYNTHETIC DATA FROM SIMULATOR")
print("=" * 70)

# Load simulator config
with open(REPO / "simulator" / "config.yaml") as f:
    raw_config = yaml.safe_load(f)

# Configure for realistic demo — anchor to today so API date.today() always hits real data
raw_config["days"] = 60
raw_config["start_date"] = (date.today() - timedelta(days=59)).isoformat()
raw_config["dt_count"] = 8
raw_config["meters_per_dt"] = 6
# Theft starts after day 20 so z-score has 20 clean baseline days
raw_config["theft_scenarios"] = [
    # DT1 (ZoneA) - 3 meters, hook bypass → HIGH risk (L1+L2+L3 all trigger)
    {"meter_id": "DT1-M03", "kind": "hook_bypass", "start_day": 20, "end_day": 60, "severity": 0.95},
    {"meter_id": "DT1-M05", "kind": "hook_bypass", "start_day": 20, "end_day": 60, "severity": 0.92},
    {"meter_id": "DT1-M06", "kind": "meter_stop", "start_day": 22, "end_day": 60, "severity": 0.90},
    # DT3 (ZoneC) - 2 meters → HIGH risk
    {"meter_id": "DT3-M01", "kind": "hook_bypass", "start_day": 18, "end_day": 60, "severity": 0.93},
    {"meter_id": "DT3-M03", "kind": "gradual_tampering", "start_day": 20, "end_day": 60, "severity": 0.88},
    # DT5 (ZoneE) - 2 meters → MEDIUM risk
    {"meter_id": "DT5-M02", "kind": "hook_bypass", "start_day": 25, "end_day": 60, "severity": 0.85},
    {"meter_id": "DT5-M04", "kind": "gradual_tampering", "start_day": 25, "end_day": 60, "severity": 0.80},
    # DT7 (ZoneG) - 2 meters → HIGH risk
    {"meter_id": "DT7-M05", "kind": "hook_bypass", "start_day": 20, "end_day": 60, "severity": 0.94},
    {"meter_id": "DT7-M03", "kind": "meter_stop", "start_day": 21, "end_day": 60, "severity": 0.91},
    # DT2 (ZoneB) - 1 meter → REVIEW
    {"meter_id": "DT2-M02", "kind": "gradual_tampering", "start_day": 30, "end_day": 60, "severity": 0.72},
    # DT4 (ZoneD) - 2 meters → MEDIUM
    {"meter_id": "DT4-M02", "kind": "hook_bypass", "start_day": 28, "end_day": 60, "severity": 0.82},
    {"meter_id": "DT4-M04", "kind": "gradual_tampering", "start_day": 28, "end_day": 60, "severity": 0.78},
    # DT6 (ZoneF) - 1 meter → HIGH (L1+L2 already fire; early start for L3 too)
    {"meter_id": "DT6-M04", "kind": "hook_bypass", "start_day": 18, "end_day": 60, "severity": 0.93},
    # DT8 (ZoneH) - single meter, extreme theft → HIGH risk (L1+L2+L3)
    {"meter_id": "DT8-M02", "kind": "hook_bypass", "start_day": 18, "end_day": 60, "severity": 0.96},
]

config = SimConfig.from_dict(raw_config)

print(f"\n[1] Generating synthetic data...")
dataset = build_dataset(config)
meter_readings = dataset["meter_readings"]
print(f"    Generated {len(meter_readings)} meter readings")

# Convert to API format
print(f"\n[2] Preparing data for ingestion...")
api_readings = []
for _, row in meter_readings.iterrows():
    kwh = float(row["kwh"])
    # Handle invalid float values
    if not pd.isna(kwh) and abs(kwh) < 1e10:
        api_readings.append({
            "meter_id": row["meter_id"],
            "timestamp": row["ts"].isoformat(),
            "kwh": kwh,
            "voltage": 230.0,
            "pf": 0.95,
        })

# Batch ingest (chunk to avoid timeout)
BATCH_SIZE = 100
print(f"\n[3] Ingesting data via API in batches of {BATCH_SIZE}...")

total_ingested = 0
for i in range(0, len(api_readings), BATCH_SIZE):
    batch = api_readings[i:i+BATCH_SIZE]
    try:
        response = requests.post(
            f"{BASE_URL}/api/v1/ingest/batch",
            json=batch,
            timeout=30
        )
        if response.ok:
            result = response.json()
            total_ingested += result["records_written"]
            print(f"    Batch {i//BATCH_SIZE + 1}: {result['records_written']} records written")
        else:
            print(f"    Batch {i//BATCH_SIZE + 1}: ERROR {response.status_code}")
            print(f"    {response.text}")
    except Exception as e:
        print(f"    Batch {i//BATCH_SIZE + 1}: ERROR - {e}")

# Transformer input readings feed the energy-balance layer (L0).
dt_rows = [{"dt_id": r.dt_id, "timestamp": r.ts.isoformat(), "kwh_in": float(r.kwh_in)}
           for r in dataset["dt_readings"].itertuples(index=False)]
for i in range(0, len(dt_rows), 1000):
    requests.post(f"{BASE_URL}/api/v1/ingest/dt-batch", json=dt_rows[i:i + 1000], timeout=30)
print(f"    Ingested {len(dt_rows)} transformer readings")

print(f"\n[4] Summary:")
print(f"    Total records generated: {len(api_readings)}")
print(f"    Total records ingested: {total_ingested}")
print(f"    Success rate: {(total_ingested/len(api_readings)*100):.1f}%")

print(f"\n[5] Available meter IDs for lookup:")
unique_meters = meter_readings["meter_id"].unique()
for meter in unique_meters[:10]:  # Show first 10
    print(f"    - {meter}")
if len(unique_meters) > 10:
    print(f"    ... and {len(unique_meters) - 10} more")

print("\n" + "=" * 70)
print("INGESTION COMPLETE")
print("=" * 70)
print("\nYou can now test the application at:")
print(f"  - Dashboard: http://localhost:5173")
print(f"  - API Docs: {BASE_URL}/docs")
print(f"\nTry looking up meter: {unique_meters[0]}")
