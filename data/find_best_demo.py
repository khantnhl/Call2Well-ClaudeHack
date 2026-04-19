"""
Finds the best demo location and service type for ClearPath.
Analyzes la_clinics_enriched.csv and uses Claude to recommend
the optimal ZIP code + service combination for the demo.
"""

import csv
import json
import math
import os
from collections import defaultdict
import anthropic

client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])


def distance_miles(lat1, lng1, lat2, lng2):
    """Haversine distance in miles."""
    R = 3958.8
    lat1, lng1, lat2, lng2 = map(math.radians, [lat1, lng1, lat2, lng2])
    dlat = lat2 - lat1
    dlng = lng2 - lng1
    a = math.sin(dlat/2)**2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlng/2)**2
    return R * 2 * math.asin(math.sqrt(a))


def main():
    # Load enriched clinics
    with open("la_clinics_enriched.csv", newline="") as f:
        clinics = [r for r in csv.DictReader(f)
                   if r["lat"] and r["lng"] and r["lat"] != "" and r["lng"] != ""]

    print(f"Loaded {len(clinics)} clinics with coordinates")

    # Convert coords
    for c in clinics:
        c["lat"] = float(c["lat"])
        c["lng"] = float(c["lng"])
        c["services_list"] = [s.strip() for s in c["services"].split(",")]
        c["languages_list"] = [l.strip() for l in c["languages"].split(",")]

    # For each clinic as a "demo caller location", find nearby clinics by service
    # Focus on dental (most specific, most emotional for demo)
    service_types = ["dental", "mental_health", "primary_care"]
    results = []

    for anchor in clinics:
        for service in service_types:
            nearby = []
            for c in clinics:
                if c["name"] == anchor["name"]:
                    continue
                if service not in c["services_list"]:
                    continue
                dist = distance_miles(anchor["lat"], anchor["lng"], c["lat"], c["lng"])
                if dist <= 10:
                    nearby.append({
                        "name": c["name"],
                        "address": c["address"],
                        "zip": c["zip"],
                        "phone": c["phone"],
                        "distance_miles": round(dist, 2),
                        "languages": c["languages_list"],
                        "hours_per_week": c["hours_per_week"]
                    })

            if len(nearby) >= 3:
                nearby_sorted = sorted(nearby, key=lambda x: x["distance_miles"])[:5]
                results.append({
                    "demo_zip": anchor["zip"].split("-")[0],
                    "demo_area": anchor["address"] + ", " + anchor["city"],
                    "service": service,
                    "clinic_count_within_10mi": len(nearby),
                    "top_clinics": nearby_sorted
                })

    # Deduplicate by zip+service, keep best (most clinics)
    best = {}
    for r in results:
        key = (r["demo_zip"], r["service"])
        if key not in best or r["clinic_count_within_10mi"] > best[key]["clinic_count_within_10mi"]:
            best[key] = r

    # Show breakdown by service
    by_service = defaultdict(list)
    for v in best.values():
        by_service[v["service"]].append(v)

    print("\nClinics found by service type:")
    for svc, items in by_service.items():
        print(f"  {svc}: {len(items)} ZIP codes with 3+ clinics within 10mi")

    # Get top 5 per service type, prioritizing dental for demo
    top_candidates = []
    for svc in ["dental", "mental_health", "primary_care"]:
        top_candidates += sorted(by_service.get(svc, []),
                                  key=lambda x: x["clinic_count_within_10mi"],
                                  reverse=True)[:5]

    print(f"\nTop candidates per service:")
    for i, c in enumerate(top_candidates[:15]):
        print(f"  {i+1}. ZIP {c['demo_zip']} | {c['service']} | {c['clinic_count_within_10mi']} clinics within 10mi")

    # Ask Claude to pick the best demo scenario
    print("\nAsking Claude to pick the best demo scenario...")

    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1024,
        messages=[{
            "role": "user",
            "content": f"""We are demoing ClearPath — a voice AI that helps uninsured Americans find free clinics.
The demo persona is Maria: 28, Uber driver, $1,800/month income, sick, no insurance, in Los Angeles.

Pick the BEST demo scenario from these candidates. Consider:
1. Emotional resonance — does the location feel real and relatable for an uninsured LA resident?
2. Service type — dental is most dramatic (tooth infection is urgent-feeling but not life-threatening)
3. Clinic density — more nearby clinics = better ranking demo
4. Spanish support — Maria could be Spanish-speaking, adds multilingual story
5. Demo clarity — judges need to immediately understand the value

Candidates:
{json.dumps(top_candidates, indent=2)}

Return JSON only:
{{
  "best_zip": "...",
  "best_service": "...",
  "reason": "2-3 sentence explanation of why this is the best demo scenario",
  "demo_neighborhood": "human-readable neighborhood name (e.g. East LA, Boyle Heights)",
  "top_3_clinics": [the 3 best clinics from that scenario's top_clinics array],
  "demo_user_statement": "the exact sentence Maria would say when calling (natural, in character)"
}}"""
        }]
    )

    raw = message.content[0].text.strip()
    print(f"\nClaude raw response:\n{raw}\n")
    # Strip markdown code blocks
    if "```" in raw:
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()
    result = json.loads(raw)

    print("\n" + "="*60)
    print("BEST DEMO SCENARIO")
    print("="*60)
    print(f"ZIP:          {result['best_zip']}")
    print(f"Service:      {result['best_service']}")
    print(f"Neighborhood: {result['demo_neighborhood']}")
    print(f"Reason:       {result['reason']}")
    print(f"\nMaria says: \"{result['demo_user_statement']}\"")
    print(f"\nTop 3 clinics:")
    for i, c in enumerate(result["top_3_clinics"]):
        print(f"  {i+1}. {c['name']}")
        print(f"     {c['address']} ({c['distance_miles']} mi)")
        print(f"     {c['phone']}")

    # Save result
    with open("demo_scenario.json", "w") as f:
        json.dump(result, f, indent=2)
    print("\nSaved to demo_scenario.json")


if __name__ == "__main__":
    main()
