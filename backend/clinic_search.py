"""
Supabase clinic search and ranking.
Step 1: Score-based pre-filter → top 5 candidates
Step 2: Return candidates to Claude for final reasoning
"""

import math
import os
from supabase import create_client

supabase = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_ANON_KEY"])


def distance_miles(lat1, lng1, lat2, lng2):
    """Haversine distance in miles."""
    R = 3958.8
    lat1, lng1, lat2, lng2 = map(math.radians, [float(lat1), float(lng1), float(lat2), float(lng2)])
    dlat, dlng = lat2 - lat1, lng2 - lng1
    a = math.sin(dlat/2)**2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlng/2)**2
    return R * 2 * math.asin(math.sqrt(a))


def zip_to_coords(zip_code):
    """
    Approximate lat/lng for common LA ZIP codes.
    In production this would use a geocoding API.
    """
    zip_coords = {
        "90001": (33.9731, -118.2479), "90002": (33.9494, -118.2461),
        "90003": (33.9644, -118.2731), "90004": (34.0761, -118.3085),
        "90005": (34.0592, -118.3017), "90006": (34.0502, -118.2930),
        "90007": (34.0275, -118.2840), "90008": (34.0084, -118.3441),
        "90010": (34.0617, -118.3085), "90011": (33.9997, -118.2587),
        "90012": (34.0609, -118.2387), "90013": (34.0427, -118.2432),
        "90014": (34.0427, -118.2539), "90015": (34.0353, -118.2697),
        "90016": (34.0195, -118.3551), "90017": (34.0502, -118.2697),
        "90018": (34.0143, -118.3152), "90019": (34.0502, -118.3441),
        "90020": (34.0699, -118.3085), "90021": (34.0341, -118.2324),
        "90022": (34.0232, -118.1527), "90023": (34.0232, -118.1960),
        "90024": (34.0631, -118.4452), "90025": (34.0427, -118.4452),
        "90026": (34.0761, -118.2587), "90027": (34.1005, -118.2924),
        "90028": (34.1005, -118.3271), "90029": (34.0895, -118.2924),
        "90031": (34.0895, -118.2109), "90032": (34.0895, -118.1741),
        "90033": (34.0502, -118.2109), "90034": (34.0232, -118.3988),
        "90035": (34.0502, -118.3826), "90036": (34.0761, -118.3441),
        "90037": (34.0011, -118.2840), "90038": (34.0895, -118.3271),
        "90039": (34.1127, -118.2587), "90040": (33.9994, -118.1413),
        "90041": (34.1348, -118.2109), "90042": (34.1127, -118.1960),
        "90043": (33.9869, -118.3271), "90044": (33.9607, -118.3085),
        "90045": (33.9607, -118.3988), "90046": (34.1005, -118.3551),
        "90047": (33.9607, -118.3152), "90057": (34.0617, -118.2840),
        "90058": (33.9994, -118.2109), "90059": (33.9244, -118.2479),
        "90061": (33.9244, -118.2840), "90062": (33.9994, -118.3085),
        "90063": (34.0341, -118.1741), "90064": (34.0341, -118.4268),
        "90065": (34.1127, -118.2324), "90066": (34.0011, -118.4268),
        "90067": (34.0617, -118.4085), "90068": (34.1127, -118.3388),
    }
    coords = zip_coords.get(zip_code[:5])
    if coords:
        return coords
    # Default to central LA if ZIP not found
    return (34.0522, -118.2437)


def score_clinic(clinic, user_lat, user_lng, service_type, language):
    """Score a clinic for ranking."""
    score = 0

    # Service match (most important)
    services = clinic.get("services") or []
    if service_type in services:
        score += 40
    elif "primary_care" in services:
        score += 10  # partial credit

    # Distance score (closer = better, max 10 miles)
    if clinic.get("lat") and clinic.get("lng"):
        dist = distance_miles(user_lat, user_lng, clinic["lat"], clinic["lng"])
        score += 30 * max(0, (10 - dist) / 10)
        clinic["distance_miles"] = round(dist, 1)
    else:
        clinic["distance_miles"] = None

    # Language match
    languages = clinic.get("languages") or []
    if language and language.lower() in [l.lower() for l in languages]:
        score += 20

    # Full-time bonus
    hours = clinic.get("hours_per_week") or 0
    if float(hours) >= 40:
        score += 10

    # Manual boost
    score += clinic.get("score_boost") or 0

    return score


def find_clinics(zip_code: str, service_type: str, language: str = "english") -> list:
    """
    Query Supabase for clinics, score them, return top 5 for Claude to reason over.
    """
    # Fetch all clinics (306 rows — small enough to filter in Python)
    response = supabase.table("clinics").select("*").execute()
    clinics = response.data

    if not clinics:
        return []

    user_lat, user_lng = zip_to_coords(zip_code)

    # Score all clinics
    scored = []
    for clinic in clinics:
        s = score_clinic(clinic, user_lat, user_lng, service_type, language)
        scored.append((s, clinic))

    # Sort by score, return top 5
    scored.sort(key=lambda x: x[0], reverse=True)
    top5 = []
    for score, clinic in scored[:5]:
        top5.append({
            "name": clinic["name"],
            "address": clinic["address"],
            "city": clinic["city"],
            "zip": clinic["zip"],
            "phone": clinic["phone"],
            "website": clinic["website"],
            "distance_miles": clinic.get("distance_miles"),
            "services": clinic.get("services") or [],
            "languages": clinic.get("languages") or [],
            "hours_per_week": clinic.get("hours_per_week"),
            "score": round(score, 1),
        })

    return top5
