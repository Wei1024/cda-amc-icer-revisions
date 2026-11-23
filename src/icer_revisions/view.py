"""A local viewer for extraction results: the review's selected-page PDFs on the left, each extractor's fields on
the right, and every evidence quote linked to a highlight on its page.

`icer view` starts a small web server on this machine only (127.0.0.1) and opens the browser. The page is static
HTML and JavaScript in `viewer/`, drawing PDFs with PDF.js; this module serves the files and a JSON summary of
each review. Quote positions are found in Python (`locate.py`), so the page only draws boxes. Nothing is sent
anywhere else, and the PDFs never leave this machine.
"""

import json
import re
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

from . import config
from .locate import locate_all
from .schema import GROUPS

STATIC = Path(__file__).parent / "viewer"
FILES = {"/": "index.html", "/viewer.js": "viewer.js", "/viewer.css": "viewer.css"}
TYPES = {".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".pdf": "application/pdf"}
PROJECT = re.compile(r"[A-Z]{2}\d{4}-\d{3}")


def fields() -> list[dict]:
    """The fields in schema order, by group, with the description the model was given."""
    return [
        {
            "group": group,
            "fields": [
                {"name": name, "description": f.description or ""}
                for name, f in model.model_fields.items()
                if name not in ("evidence", "notes")
            ],
        }
        for group, model in GROUPS.items()
    ]


def _fields(item: dict) -> dict:
    """Records made before quotes could support several fields name one `field`."""
    if "fields" in item:
        return item
    item = dict(item)
    return item | {"fields": [item.pop("field")]}


def _row_labels(values: dict) -> list[dict]:
    """The stepped table's title and row labels are verbatim, so each is located like a quote."""
    if not values.get("table_document") or not values.get("table_page"):
        return []
    where = {"document": values["table_document"], "page": values["table_page"], "table": True}
    items = [{"fields": ["table_title"], "quote": values["table_title"]} | where] if values.get("table_title") else []
    return items + [
        {"fields": ["rows"], "quote": row["label"], "row": row["order"]} | where for row in values.get("rows") or []
    ]


def reviews(extractions: Path = config.EXTRACTIONS, pages: Path = config.PAGES) -> list[dict]:
    """Reviews that have selected pages and at least one extraction record."""
    found: dict[str, list[str]] = {}
    for path in sorted(extractions.glob("*/*.json")):
        if (pages / path.stem).is_dir():
            found.setdefault(path.stem, []).append(path.parent.name)
    return [{"project": p, "extractors": ids} for p, ids in sorted(found.items())]


def review(project: str, extractions: Path = config.EXTRACTIONS, pages: Path = config.PAGES) -> dict:
    """Everything the page shows for one review: its documents and each extractor's record, quotes located."""
    docs = [k for k in ("rec", "pe", "clin") if (pages / project / f"{k}.pdf").exists()]
    out = []
    for path in sorted(extractions.glob(f"*/{project}.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        record = json.loads(path.read_text())
        calls = record.get("calls") or {}
        # a failed review still shows the groups that succeeded
        values, evidence, notes = {}, [], []
        for group, call in calls.items():
            if output := call.get("output"):
                output = dict(output)
                evidence += output.pop("evidence", [])
                if note := output.pop("notes", "").strip():
                    notes.append({"group": group, "text": note})
                values |= output
        evidence += _row_labels(values)
        out.append(
            {
                "id": path.parent.name,
                "model": record.get("model"),
                "error": record.get("error"),
                "cost_usd": sum((c.get("usage") or {}).get("cost_usd") or 0 for c in calls.values()),
                "updated": path.stat().st_mtime,
                "calls": {
                    g: {k: c.get(k) for k in ("error", "seconds", "provider", "usage", "finish_reason")}
                    for g, c in calls.items()
                },
                "values": values,
                "evidence": locate_all([_fields(e) for e in evidence], pages / project),
                "notes": notes,
            }
        )
    return {"project": project, "documents": docs, "fields": fields(), "extractors": out}


class Handler(BaseHTTPRequestHandler):
    extractions, pages = config.EXTRACTIONS, config.PAGES

    def log_message(self, *args) -> None:  # keep the terminal quiet
        pass

    def _send(self, body: bytes, kind: str, status: HTTPStatus = HTTPStatus.OK) -> None:
        self.send_response(status)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, data) -> None:
        self._send(json.dumps(data).encode(), "application/json")

    def do_GET(self) -> None:
        path = unquote(urlparse(self.path).path)
        if path in FILES:
            file = STATIC / FILES[path]
            return self._send(file.read_bytes(), TYPES[file.suffix] + "; charset=utf-8")
        if path == "/api/reviews":
            return self._json(reviews(self.extractions, self.pages))
        if (m := re.fullmatch(r"/api/review/([^/]+)", path)) and PROJECT.fullmatch(m[1]):
            return self._json(review(m[1], self.extractions, self.pages))
        if (m := re.fullmatch(r"/pdf/([^/]+)/(rec|pe|clin)\.pdf", path)) and PROJECT.fullmatch(m[1]):
            file = self.pages / m[1] / f"{m[2]}.pdf"
            if file.exists():
                return self._send(file.read_bytes(), TYPES[".pdf"])
        self._send(b"not found", "text/plain", HTTPStatus.NOT_FOUND)


def serve(project: str | None = None, port: int = 8765, open_browser: bool = True) -> None:
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    url = f"http://127.0.0.1:{port}/" + (f"#{project}" if project else "")
    print(f"viewer at {url} (Ctrl+C to stop)")
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
