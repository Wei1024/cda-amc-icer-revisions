"""Run one LLM extractor over reviews: each review's selected-page PDFs in, one validated record out.

Each review takes four calls, one per field group (`schema.GROUPS`). Every call sends the same prefix, the
instructions and the review's PDFs, with a cache breakpoint after the last PDF; only the final message, naming the
group and giving its JSON schema, differs. So the first call writes the cache and the other three read the PDFs
from it. The schema goes in that message rather than in `response_format`, because providers treat an output
schema as part of the prompt prefix: a different schema per call would invalidate the cache (Anthropic documents
this). The reply is validated against the schema in code, and an invalid reply fails that call.

Calls go through OpenRouter's chat completions API, so an extractor can be any model OpenRouter serves. Each
extractor is a named model + effort setting, optionally pinned to one provider. Three settings keep the two
extractors comparable:
- PDFs are sent with the `native` engine, so the model reads the pages themselves. A model without native file
  input fails instead of silently getting OCR text.
- `require_parameters` routes only to providers that support every request parameter, and provider fallbacks are
  off when a provider is pinned. The record keeps the model and provider that actually answered.
- The instructions are the role text below plus spec §2 and §3, read from docs/extraction-spec.md at run time. A
  hash of the instructions and the JSON schema is part of the extractor id, so a change to either starts a fresh
  set of outputs instead of mixing old and new.

One JSON file per review and extractor, under data/extractions/<extractor id>/, holding each call's output and
the merged record. Re-runs skip reviews that are complete and repeat only the calls that failed. Comparing two
extractors and adjudicating their disagreements are separate steps.
"""

import base64
import hashlib
import json
import os
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import requests
from pydantic import ValidationError

from . import config
from .schema import GROUPS, merge

SPEC = config.ROOT / "docs" / "extraction-spec.md"
URL = "https://openrouter.ai/api/v1/chat/completions"

ROLE = """You extract data from Canadian Drug Agency (CDA-AMC, formerly CADTH) reimbursement reviews.

The attached documents are selected pages of one review, each labelled before it: `rec` (the Recommendation),
`pe` (the economic, or combined clinical and economic, report) and, for some reviews, `clin` (the separate
clinical report). Fill every field of the output schema from these pages only.

- When the pages do not give a value, use null, or the field's "not reported" or "unclear" code. Never guess.
- Follow the field definitions and the numbered rules below. When a rule decides a value, say so in `notes`
  with its number (for example "rule 5: used the revised sponsor base case").
- Submission features describe what the sponsor submitted. Never take them from the agency's critique.
- `evidence` quotes are verbatim. Give the document they come from and the page within that attached document
  (its first page is 1).

The field definitions and rules follow."""


def instructions(spec: Path = SPEC) -> str:
    """The role text plus spec §2 (output fields) and §3 (rules for hard cases)."""
    text = spec.read_text()
    start, end = text.index("## 2. Output"), text.index("## 4. Computed in code")
    return f"{ROLE}\n\n{text[start:end].strip()}\n"


SYSTEM = instructions()
SECTIONS = {"icers": "§2.1 and §2.2", "stepwise": "§2.3", "features": "§2.4", "price": "§2.5"}


def _group_prompt(group: str) -> str:
    fields = ", ".join(f for f in GROUPS[group].model_fields if f not in ("evidence", "notes"))
    schema = json.dumps(GROUPS[group].model_json_schema(), separators=(",", ":"))
    return (
        f"Fill the `{group}` fields (spec {SECTIONS[group]}): {fields}. "
        "Give evidence and notes for these fields only.\n"
        f"Reply with only a JSON object that matches this JSON schema, with no other text:\n{schema}"
    )


GROUP_PROMPTS = {g: _group_prompt(g) for g in GROUPS}
PROMPT_VERSION = hashlib.sha256(json.dumps([SYSTEM, GROUP_PROMPTS], sort_keys=True).encode()).hexdigest()[:8]

MAX_PDF_BYTES = 22_000_000  # all documents together; base64 adds a third
DOC_LABELS = {"rec": "Recommendation", "pe": "Economic report", "clin": "Clinical report"}
RETRYABLE = {408, 429, 502, 503, 504, 524, 529}


@dataclass(frozen=True)
class Extractor:
    name: str
    model: str  # an OpenRouter model id, e.g. "anthropic/claude-opus-5.5"
    effort: str = "high"
    provider: str | None = None  # pin one provider, e.g. "anthropic"; None lets OpenRouter choose

    @property
    def id(self) -> str:
        return f"{self.name}-{self.model.replace('/', '_')}-{PROMPT_VERSION}"


# Extractor B (a different model family, spec §5) is added here once it is chosen.
EXTRACTORS = {
    "a": Extractor("a", "anthropic/claude-opus-5.5", provider="anthropic"),
    "haiku-test": Extractor("haiku-test", "anthropic/claude-haiku-5.5", effort="medium", provider="anthropic"),
}


def api_key() -> str:
    """OPENROUTER_API_KEY from the environment, or from the repo's .env file (see .env.example)."""
    if key := os.environ.get("OPENROUTER_API_KEY"):
        return key
    env = config.ROOT / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            name, _, value = line.partition("=")
            if name.strip() == "OPENROUTER_API_KEY" and value.strip():
                return value.strip().strip("\"'")
    raise SystemExit("OPENROUTER_API_KEY is not set: copy .env.example to .env and add your key")


def review_docs(pages_dir: Path, project: str) -> dict[str, Path]:
    """The review's selected-page PDFs that exist, in the order they are sent."""
    return {k: p for k in DOC_LABELS if (p := pages_dir / project / f"{k}.pdf").exists()}


def document_parts(docs: dict[str, Path]) -> list[dict]:
    """The labelled PDFs, ending in a cache breakpoint. Built once per review, so every call's prefix is identical."""
    parts = []
    for kind, path in docs.items():
        data = base64.standard_b64encode(path.read_bytes()).decode()
        parts.append({"type": "text", "text": f"Document `{kind}`: {DOC_LABELS[kind]}"})
        parts.append(
            {"type": "file", "file": {"filename": f"{kind}.pdf", "file_data": f"data:application/pdf;base64,{data}"}}
        )
    parts.append({"type": "text", "text": "End of documents.", "cache_control": {"type": "ephemeral"}})
    return parts


def request_body(extractor: Extractor, project: str, group: str, documents: list[dict]) -> dict:
    provider = {"require_parameters": True}
    if extractor.provider:
        provider |= {"order": [extractor.provider], "allow_fallbacks": False}
    prompt = {"type": "text", "text": f"Review {project}. {GROUP_PROMPTS[group]}"}
    return {
        "model": extractor.model,
        "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": [*documents, prompt]}],
        "plugins": [{"id": "file-parser", "pdf": {"engine": "native"}}],
        "provider": provider,
        "reasoning": {"effort": extractor.effort},
        "max_tokens": 32000,
    }


Post = Callable[[dict], tuple[int, dict, dict]]  # body -> (HTTP status, response JSON, headers)


def http_post(key: str, timeout: float = 900) -> Post:
    session = requests.Session()
    session.headers.update({"Authorization": f"Bearer {key}", "X-OpenRouter-Title": "icer-revisions"})

    def post(body: dict) -> tuple[int, dict, dict]:
        resp = session.post(URL, json=body, timeout=timeout)
        try:
            data = resp.json()
        except ValueError:
            data = {"error": {"code": resp.status_code, "message": resp.text[:300]}}
        return resp.status_code, data, dict(resp.headers)

    return post


def _send(post: Post, body: dict, retries: int = 3) -> tuple[int, dict]:
    """POST with retries for rate limits, timeouts and provider outages, honouring Retry-After."""
    for attempt in range(retries + 1):
        try:
            status, data, headers = post(body)
        except requests.RequestException as e:
            status, data, headers = 0, {"error": {"code": 0, "message": f"connection: {e}"}}, {}
        # a provider failure after the headers were sent arrives as HTTP 200 with only an error
        code = data["error"].get("code", status) if "error" in data and not data.get("choices") else status
        if code not in RETRYABLE and status != 0:
            return status, data
        if attempt < retries:
            time.sleep(float(headers.get("Retry-After") or 2 ** (attempt + 1)))
    return status, data


def _usage(data: dict) -> dict:
    u = data.get("usage") or {}
    return {
        "prompt_tokens": u.get("prompt_tokens"),
        "completion_tokens": u.get("completion_tokens"),
        "cached_tokens": (u.get("prompt_tokens_details") or {}).get("cached_tokens"),
        "cache_write_tokens": (u.get("prompt_tokens_details") or {}).get("cache_write_tokens"),
        "reasoning_tokens": (u.get("completion_tokens_details") or {}).get("reasoning_tokens"),
        "cost_usd": u.get("cost"),  # OpenRouter credits, 1 credit = $1
    }


def _json_text(content: str | None) -> str:
    """The JSON object in a reply, without a Markdown code fence around it."""
    text = (content or "").strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1].rsplit("```", 1)[0]
    return text.strip()


def call_group(post: Post, extractor: Extractor, project: str, group: str, documents: list[dict]) -> dict:
    """One call for one field group: {output, error, and the call's metadata}."""
    status, data = _send(post, request_body(extractor, project, group, documents))
    if "error" in data and not data.get("choices"):
        err = data["error"]
        kind = (err.get("metadata") or {}).get("error_type") or f"http_{err.get('code', status)}"
        return {"error": f"{kind}: {err.get('message', '')[:300]}", "output": None}
    choice = data["choices"][0]
    call = {
        "served_by": data.get("model"),
        "provider": data.get("provider"),
        "generation_id": data.get("id"),
        "finish_reason": choice.get("finish_reason"),
        "usage": _usage(data),
    }
    if choice.get("finish_reason") != "stop":  # "length": output cut off; "content_filter": refused
        return call | {"error": choice.get("finish_reason") or "no_finish_reason", "output": None}
    try:
        parsed = GROUPS[group].model_validate_json(_json_text(choice["message"]["content"]))
    except ValidationError as e:
        return call | {"error": f"invalid_output: {e.error_count()} errors", "output": None}
    return call | {"error": None, "output": parsed.model_dump(mode="json")}


def extract_one(
    post: Post, extractor: Extractor, project: str, docs: dict[str, Path], previous: dict | None = None
) -> dict:
    """All four calls for one review, reusing groups that succeeded in `previous`. Always returns a record;
    `error` is set unless every group succeeded."""
    record = {"project": project, "extractor_id": extractor.id, "model": extractor.model, "documents": list(docs)}
    if sum(p.stat().st_size for p in docs.values()) > MAX_PDF_BYTES:
        return record | {"error": "pdf_too_large", "calls": {}, "extraction": None}
    calls = {g: c for g, c in ((previous or {}).get("calls") or {}).items() if c.get("error") is None}
    documents = None
    for group in GROUPS:
        if group not in calls:
            documents = documents or document_parts(docs)
            calls[group] = call_group(post, extractor, project, group, documents)
    errors = [f"{g}: {c['error']}" for g, c in calls.items() if c["error"]]
    costs = [(c.get("usage") or {}).get("cost_usd") or 0 for c in calls.values()]
    record |= {"calls": {g: calls[g] for g in GROUPS}, "cost_usd": round(sum(costs), 6)}
    if errors:
        return record | {"error": "; ".join(errors), "extraction": None}
    parts = {g: GROUPS[g].model_validate(calls[g]["output"]) for g in GROUPS}
    return record | {"error": None, "extraction": merge(parts).model_dump(mode="json")}


def out_path(extractor: Extractor, project: str, out_dir: Path = config.EXTRACTIONS) -> Path:
    return out_dir / extractor.id / f"{project}.json"


def done(path: Path) -> bool:
    return path.exists() and json.loads(path.read_text()).get("error") is None


def run(
    cohort: pd.DataFrame,
    extractor: Extractor,
    pages_dir: Path = config.PAGES,
    out_dir: Path = config.EXTRACTIONS,
    post: Post | None = None,
) -> pd.DataFrame:
    """Extract every review in `cohort` that has selected pages and no successful record yet; return a summary."""
    post = post or http_post(api_key())
    rows = []
    for project in cohort["project"]:
        dest = out_path(extractor, project, out_dir)
        docs = review_docs(pages_dir, project)
        if done(dest):
            status = "cached"
        elif not docs:
            status = "no_pages"
        else:
            previous = json.loads(dest.read_text()) if dest.exists() else None
            record = extract_one(post, extractor, project, docs, previous)
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(json.dumps(record, indent=2))
            status = record["error"] or "ok"
            print(f"  {project}: {status} (${record.get('cost_usd') or 0:.4f})")
        rows.append({"project": project, "status": status})
    summary = pd.DataFrame(rows)
    print(f"extract {extractor.id}: {summary.status.value_counts().to_dict()}")
    return summary
