"""Rehearsal demo: authenticated task ingress, no models needed.

Builds only the ingest router over a temporary real SQLite store, then walks
the four cases the acceptance item names and prints the console task table.

Run:  python -m scripts.demo_task_ingest

For the live version, start the host with INGEST_SOURCE_TOKENS set and:
    curl -i -X POST http://<host>:8765/v1/tasks/ingest \
      -H "Authorization: Bearer <token>" -H "Content-Type: application/json" \
      -d '{"source":"email-sim","external_id":"msg-001","title":"Send report",
           "created_at":"2026-09-24T08:00:00+08:00"}'
then:  python -m scripts.show_tasks
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.http import tasks
from scripts.show_tasks import format_events, format_tasks
from storage.sqlite_store import SQLiteStore

TOKEN = "demo-connector-token-123456"
BODY = {
    "source": "email-sim", "external_id": "msg-001", "title": "Send the weekly report",
    "priority": "high", "due_at": "2026-10-01T09:00:00+08:00",
    "created_at": "2026-09-24T08:00:00+08:00",
}


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        store = SQLiteStore(str(Path(tmp) / "demo.db"))
        app = FastAPI()
        app.include_router(tasks.router)
        app.state.ingest_deps = tasks.IngestDeps(store=store, source_tokens={"email-sim": TOKEN})
        client = TestClient(app)
        good = {"Authorization": f"Bearer {TOKEN}"}

        cases = [
            ("valid request           ", client.post("/v1/tasks/ingest", json=BODY, headers=good)),
            ("same (source, ext_id)   ", client.post("/v1/tasks/ingest", json=BODY, headers=good)),
            ("no token                ", client.post("/v1/tasks/ingest", json=BODY)),
            ("unknown field           ", client.post("/v1/tasks/ingest", json={**BODY, "x": 1}, headers=good)),
            ("missing title           ", client.post("/v1/tasks/ingest", json={k: v for k, v in BODY.items() if k != "title"}, headers=good)),
        ]
        for label, response in cases:
            print(f"[ingest] {label} -> {response.status_code}")
        print()
        print(format_tasks(store.list_tasks()))
        print()
        print(format_events(store.list_ingress_events()))


if __name__ == "__main__":
    main()
