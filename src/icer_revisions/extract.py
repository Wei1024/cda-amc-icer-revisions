"""Run one LLM extractor over reviews: a PDF of each review's selected pages in, one validated record out.

Each extractor is a named model + effort setting. The instructions are the role text below plus spec §2 and §3,
read from docs/extraction-spec.md at run time, so the prompt and the spec cannot drift apart. The prompt version
is a hash of the instructions and the JSON schema; it is part of the extractor id, so a change to either starts a
fresh set of outputs instead of mixing old and new.

One JSON file per review and extractor, under data/extractions/<extractor id>/. Re-runs skip reviews that already
have a successful record. Comparing two extractors and adjudicating their disagreements are separate steps.
"""

import base64
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

import anthropic
import pandas as pd
from pydantic import ValidationError

from . import config
from .schema import Extraction

SPEC = config.ROOT / "docs" / "extraction-spec.md"

ROLE = """You extract data from Canadian Drug Agency (CDA-AMC, formerly CADTH) reimbursement reviews.

The attached PDF holds selected pages of one review, in this order: the Recommendation, the economic (or combined
clinical and economic) report, and for some reviews the separate clinical report. Fill every field of the output
schema from these pages only.

- When the pages do not give a value, use null, or the field's "not reported" or "unclear" code. Never guess.
- Follow the field definitions and the numbered rules below. When a rule decides a value, say so in `notes`
  with its number (for example "rule 5: used the revised sponsor base case").
- Submission features describe what the sponsor submitted. Never take them from the agency's critique.
- `evidence` quotes are verbatim, and their page numbers are pages of the attached PDF (its first page is 1).

The field definitions and rules follow."""


def instructions(spec: Path = SPEC) -> str:
    """The role text plus spec §2 (output fields) and §3 (rules for hard cases)."""
    text = spec.read_text()
    start, end = text.index("## 2. Output"), text.index("## 4. Computed in code")
    return f"{ROLE}\n\n{text[start:end].strip()}\n"


SYSTEM = instructions()
SCHEMA = json.dumps(Extraction.model_json_schema(), sort_keys=True)
PROMPT_VERSION = hashlib.sha256((SYSTEM + SCHEMA).encode()).hexdigest()[:8]

# $ per million tokens: input, output, cache read. Cache writes are billed at 1.25x input (5-minute cache).
PRICES = {"claude-opus-5-5": (4.00, 20.00, 0.20)}
MAX_PDF_BYTES = 30_000_000  # the request limit is 32 MB, and base64 adds a third


@dataclass(frozen=True)
class Extractor:
    name: str
    model: str
    effort: str = "high"

    @property
    def id(self) -> str:
        return f"{self.name}-{self.model}-{PROMPT_VERSION}"


# Extractor B (a different model family, spec §5) is added here once it is chosen.
EXTRACTORS = {"a": Extractor("a", "claude-opus-5-5")}


def cost_usd(model: str, usage: dict) -> float | None:
    if model not in PRICES:
        return None
    inp, out, cache_read = PRICES[model]
    total = (
        usage["input_tokens"] * inp
        + usage["output_tokens"] * out
        + usage["cache_read_input_tokens"] * cache_read
        + usage["cache_creation_input_tokens"] * inp * 1.25
    )
    return round(total / 1e6, 4)


def _usage(response) -> dict:
    u = response.usage
    return {
        "input_tokens": u.input_tokens,
        "output_tokens": u.output_tokens,
        "cache_read_input_tokens": u.cache_read_input_tokens or 0,
        "cache_creation_input_tokens": u.cache_creation_input_tokens or 0,
    }


def extract_one(client: anthropic.Anthropic, extractor: Extractor, project: str, pdf: Path) -> dict:
    """Call the model once for one review. Always returns a record; `error` is set when there is no extraction."""
    record = {"project": project, "extractor_id": extractor.id, "model": extractor.model, "pages_pdf": pdf.name}
    if pdf.stat().st_size > MAX_PDF_BYTES:
        return record | {"error": "pdf_too_large", "extraction": None}
    data = base64.standard_b64encode(pdf.read_bytes()).decode()
    try:
        response = client.with_options(timeout=900).messages.parse(
            model=extractor.model,
            max_tokens=16000,
            system=[{"type": "text", "text": SYSTEM, "cache_control": {"type": "ephemeral"}}],
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "document",
                            "source": {"type": "base64", "media_type": "application/pdf", "data": data},
                        },
                        {"type": "text", "text": f"Review {project}: extract the record."},
                    ],
                }
            ],
            output_format=Extraction,
            output_config={"effort": extractor.effort},
        )
    except anthropic.BadRequestError as e:  # not retryable: bad PDF, request too large, ...
        return record | {"error": f"bad_request: {e.message}", "extraction": None}
    except anthropic.APIStatusError as e:  # the SDK has already retried 429 and 5xx
        return record | {"error": f"http_{e.status_code}: {e.message}", "extraction": None}
    except anthropic.APIConnectionError:
        return record | {"error": "connection", "extraction": None}

    record |= {
        "served_by": response.model,
        "request_id": response._request_id,
        "stop_reason": response.stop_reason,
        "usage": _usage(response),
    }
    record["cost_usd"] = cost_usd(extractor.model, record["usage"])
    if response.stop_reason != "end_turn":  # refusal, or max_tokens (output cut off)
        return record | {"error": response.stop_reason, "extraction": None}
    try:
        parsed = response.parsed_output
    except ValidationError as e:
        return record | {"error": f"invalid_output: {e.error_count()} errors", "extraction": None}
    if parsed is None:
        return record | {"error": "no_output", "extraction": None}
    return record | {"error": None, "extraction": parsed.model_dump(mode="json")}


def out_path(extractor: Extractor, project: str, out_dir: Path = config.EXTRACTIONS) -> Path:
    return out_dir / extractor.id / f"{project}.json"


def done(path: Path) -> bool:
    return path.exists() and json.loads(path.read_text()).get("error") is None


def run(
    cohort: pd.DataFrame,
    extractor: Extractor,
    pages_dir: Path = config.PAGES,
    out_dir: Path = config.EXTRACTIONS,
    client: anthropic.Anthropic | None = None,
) -> pd.DataFrame:
    """Extract every review in `cohort` that has a pages PDF and no successful record yet; return a summary."""
    client = client or anthropic.Anthropic()
    rows = []
    for project in cohort["project"]:
        dest = out_path(extractor, project, out_dir)
        pdf = pages_dir / f"{project}.pdf"
        if done(dest):
            status = "cached"
        elif not pdf.exists():
            status = "no_pages"
        else:
            record = extract_one(client, extractor, project, pdf)
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(json.dumps(record, indent=2))
            status = record["error"] or "ok"
            print(f"  {project}: {status} (${record.get('cost_usd') or 0:.2f})")
        rows.append({"project": project, "status": status})
    summary = pd.DataFrame(rows)
    print(f"extract {extractor.id}: {summary.status.value_counts().to_dict()}")
    return summary
