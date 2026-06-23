"""
Seed the bot with a tenant's knowledge files. Avoids PowerShell curl quoting.

Usage (with the server already running in another terminal):
    python seed.py sugamaze

It reads every .md / .txt file in ./knowledge and ingests each one under the
given tenant id (default: sugamaze), then prints the resulting chunk count.
"""
import sys
import json
import pathlib
import urllib.request
import urllib.error

API = "http://localhost:8000"
TENANT = sys.argv[1] if len(sys.argv) > 1 else "sugamaze"
KB_DIR = pathlib.Path(__file__).parent / "knowledge"


def post(path, payload):
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        API + path, data=data, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read().decode("utf-8"))


def get(path):
    with urllib.request.urlopen(API + path) as r:
        return json.loads(r.read().decode("utf-8"))


def main():
    files = sorted(KB_DIR.glob("*.md")) + sorted(KB_DIR.glob("*.txt"))
    if not files:
        print(f"No .md/.txt files found in {KB_DIR}")
        return

    try:
        get("/health")
    except urllib.error.URLError:
        print("Could not reach the API at http://localhost:8000")
        print("Start it first:  uvicorn app.main:app --reload --port 8000")
        return

    for f in files:
        text = f.read_text(encoding="utf-8")
        try:
            res = post("/ingest/text", {"tenant_id": TENANT, "source": f.name, "text": text})
            print(f"Ingested {f.name}: {res['ingested_chunks']} chunks")
        except urllib.error.HTTPError as e:
            print(f"Failed on {f.name}: {e.read().decode()}")

    print("Tenant stats:", get(f"/stats/{TENANT}"))


if __name__ == "__main__":
    main()
