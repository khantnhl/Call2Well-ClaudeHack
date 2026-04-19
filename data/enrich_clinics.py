"""
Enrich LA clinics with services and languages inferred from clinic names
using Claude API. Reads la_clinics_clean.csv, adds services/languages,
writes la_clinics_enriched.csv.
"""

import csv
import json
import os
import anthropic

client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

BATCH_SIZE = 20  # clinics per Claude call

SYSTEM_PROMPT = """You are helping enrich a database of Federally Qualified Health Centers (FQHCs) in Los Angeles.

For each clinic name provided, infer:
1. services: array from ["primary_care", "dental", "mental_health", "vision", "womens_health", "pediatrics"]
2. languages: array from ["english", "spanish", "korean", "chinese", "tagalog", "vietnamese", "armenian"]

Rules:
- ALL clinics get "primary_care" (it's required for all FQHCs)
- Add "dental" only if the name clearly suggests dental services
- Add "mental_health" only if the name suggests behavioral/mental health
- Add "spanish" to languages if the clinic is in a predominantly Spanish-speaking area or name suggests it (East LA, Boyle Heights, Pico-Aliso, Cesar Chavez, etc.)
- Default languages to ["english"] if no signals
- Be conservative — only add services/languages you're confident about

Return ONLY a JSON array, one object per clinic, in the same order as input:
[
  {"services": ["primary_care"], "languages": ["english", "spanish"]},
  ...
]"""


def enrich_batch(batch):
    """Send a batch of clinic names to Claude and get services/languages back."""
    clinic_list = "\n".join(
        f"{i+1}. {row['name']} | {row['address']} | {row['city']}"
        for i, row in enumerate(batch)
    )

    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=4096,
        messages=[{
            "role": "user",
            "content": f"Enrich these {len(batch)} LA clinics:\n\n{clinic_list}\n\nReturn JSON array only."
        }],
        system=SYSTEM_PROMPT
    )

    response_text = message.content[0].text.strip()
    # Strip markdown code blocks if present
    if response_text.startswith("```"):
        response_text = response_text.split("```")[1]
        if response_text.startswith("json"):
            response_text = response_text[4:]
    return json.loads(response_text)


def main():
    # Read cleaned clinics
    with open("la_clinics_clean.csv", newline="") as f:
        reader = csv.DictReader(f)
        clinics = list(reader)

    print(f"Enriching {len(clinics)} clinics in batches of {BATCH_SIZE}...")

    enriched = []
    for i in range(0, len(clinics), BATCH_SIZE):
        batch = clinics[i:i + BATCH_SIZE]
        print(f"  Batch {i//BATCH_SIZE + 1}/{(len(clinics) + BATCH_SIZE - 1)//BATCH_SIZE} ({len(batch)} clinics)...")

        try:
            results = enrich_batch(batch)
            for clinic, result in zip(batch, results):
                clinic["services"] = ",".join(result.get("services", ["primary_care"]))
                clinic["languages"] = ",".join(result.get("languages", ["english"]))
                enriched.append(clinic)
        except Exception as e:
            print(f"  Error in batch: {e} — using defaults")
            for clinic in batch:
                clinic["services"] = "primary_care"
                clinic["languages"] = "english"
                enriched.append(clinic)

    # Write enriched CSV
    output_path = "la_clinics_enriched.csv"
    with open(output_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=enriched[0].keys())
        writer.writeheader()
        writer.writerows(enriched)

    print(f"\nDone. Saved to {output_path}")

    # Quick stats
    dental = sum(1 for r in enriched if "dental" in r["services"])
    mental = sum(1 for r in enriched if "mental_health" in r["services"])
    spanish = sum(1 for r in enriched if "spanish" in r["languages"])
    print(f"  Dental: {dental} clinics")
    print(f"  Mental health: {mental} clinics")
    print(f"  Spanish support: {spanish} clinics")


if __name__ == "__main__":
    main()
