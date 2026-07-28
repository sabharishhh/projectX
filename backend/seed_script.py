# seed_test.py — run once before testing, from backend/
import httpx

MEMORY_URL = "http://127.0.0.1:8100"
SOURCE = "test-seed"  # tag, so these are identifiable/cleanable later

FACTS = [
    ("User enjoys watching Christopher Nolan movies.", "preference"),
    ("User likes Quentin Tarantino films.", "preference"),
    ("User's favorite actor is Cillian Murphy.", "preference"),  # trap: contains "actor", not really a "movies" request target
    ("User works as a data analyst at a fintech startup.", "identity"),  # unrelated control
    ("User is planning a trip to Japan in December.", "project"),  # unrelated control
    ("User prefers dark roast coffee.", "preference"),  # unrelated control
]

for content, unit_type in FACTS:
    r = httpx.post(f"{MEMORY_URL}/remember", json={
        "content": content, "unit_type": unit_type, "provenance": "stated",
        "source": SOURCE, "summary": content, "branch": "main",
    }, timeout=10.0)
    print(r.status_code, content)