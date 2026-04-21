"""
Seeds la_clinics_enriched.csv into Supabase clinics table.
Run from the data/ directory:
  SUPABASE_URL=... SUPABASE_ANON_KEY=... python3 seed_clinics.py
"""

import csv
import os
from supabase import create_client

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_ANON_KEY"]

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

BATCH_SIZE = 50


def parse_array(value, default):
    """Convert comma-separated string to list."""
    if not value or value.strip() == "":
        return default
    return [v.strip() for v in value.split(",") if v.strip()]


def parse_float(value):
    """Convert string to float, None if empty."""
    try:
        return float(value) if value and value.strip() else None
    except ValueError:
        return None


def main():
    with open("la_clinics_enriched.csv", newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    print(f"Loaded {len(rows)} clinics from CSV")

    records = []
    skipped = 0
    for row in rows:
        lat = parse_float(row.get("lat"))
        lng = parse_float(row.get("lng"))
        if lat is None or lng is None:
            skipped += 1
            continue

        records.append({
            "name": row["name"],
            "address": row["address"],
            "city": row["city"],
            "zip": row["zip"].split("-")[0] if row["zip"] else None,
            "phone": row["phone"],
            "website": row["website"] if row["website"] else None,
            "hours_per_week": parse_float(row.get("hours_per_week")),
            "lat": lat,
            "lng": lng,
            "services": parse_array(row.get("services"), ["primary_care"]),
            "languages": parse_array(row.get("languages"), ["english"]),
            "score_boost": int(row.get("score_boost") or 0),
        })

    print(f"Skipped {skipped} clinics with missing coordinates")
    print(f"Inserting {len(records)} clinics in batches of {BATCH_SIZE}...")

    inserted = 0
    for i in range(0, len(records), BATCH_SIZE):
        batch = records[i:i + BATCH_SIZE]
        supabase.table("clinics").insert(batch).execute()
        inserted += len(batch)
        print(f"  Inserted {inserted}/{len(records)}...")

    print(f"\nDone. {inserted} clinics seeded into Supabase.")


if __name__ == "__main__":
    main()
