"""Insert a few generic sample items so a fresh install has something to show.
Run with:  flask --app wsgi seed"""
from . import models
from .db import get_db

SAMPLE_ITEMS = [
    ("Mountain Bike", "bike", "A hardtail trail bike, tuned and ready to ride.", 12, "day", 40),
    ("Camping Tent", "tent", "Four-person tent, quick to pitch, packs down small.", 10, "day", 30),
    ("Camera Kit", "camera", "Mirrorless body, two lenses, and spare batteries.", 18, "day", 60),
    ("Cooler", "cooler", "48-quart cooler that holds ice for days.", 6, "day", 15),
]


def run():
    existing = {i["slug"] for i in models.list_items()}
    for name, slug, desc, rate, unit, deposit in SAMPLE_ITEMS:
        if slug in existing:
            continue
        models.create_item(name, slug, desc, rate, unit, deposit)
    get_db().commit()
