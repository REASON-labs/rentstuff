"""Insert a few sample items so a fresh install has something to look at.
Run with:  flask --app wsgi seed"""
from . import models
from .db import get_db

SAMPLE_ITEMS = [
    ("Ford F-150", "truck", "Half-ton pickup. Great for hauling and dump runs.",
     45, "day", 100),
    ("Starlink (Roam)", "starlink", "Portable dish + router. Internet anywhere.",
     15, "day", 50),
    ("Solar Battery Bank", "solar-battery", "Off-grid power for camping or outages.",
     20, "day", 40),
    ("Utility Trailer", "trailer", "5x8 open trailer. Bring your own straps.",
     25, "day", 75),
]


def run():
    existing = {i["slug"] for i in models.list_items()}
    for name, slug, desc, rate, unit, deposit in SAMPLE_ITEMS:
        if slug in existing:
            continue
        models.create_item(name, slug, desc, rate, unit, deposit)
    get_db().commit()
