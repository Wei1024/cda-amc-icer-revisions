"""The extraction runner, with a fake client: no API calls."""

import json

import pandas as pd
import pytest
from pydantic import ValidationError

from icer_revisions import extract
from icer_revisions.schema import Extraction

RECORD = {
    "sponsor_icer": 157293.0,
    "sponsor_icer_status": "point",
    "agency_icer": 171723.0,
    "agency_icer_status": "point",
    "agency_icer_range_low": 157226.0,
    "agency_icer_range_high": 370710.0,
    "agency_icer_headline": None,
    "comparator": "fulvestrant",
    "icer_type": "probabilistic",
    "icer_type_mismatch": False,
    "icer_basis": "pairwise",
    "sponsor_version": "original",
    "analysis_type": "cost_utility",
    "ratio_status": "ok",
    "inc_cost_sponsor": None,
    "inc_qaly_sponsor": None,
    "inc_cost_agency": None,
    "inc_qaly_agency": None,
    "inc_derived": False,
    "has_stepwise_table": True,
    "stepwise_type": "cumulative",
    "steps": [
        {
            "order": 1,
            "description": "Changed OS extrapolation",
            "category": "extrapolation_survival",
            "icer_after": 171723.0,
        }
    ],
    "pivotal_design": "rct_placebo_or_other",
    "comparison_method": "direct",
    "primary_endpoint_type": "pfs_or_efs",
    "comparator_type": "active_drug",
    "n_comparators_sponsor": 1,
    "model_type": "partitioned_survival",
    "time_horizon_years": 15.0,
    "lifetime_unspecified": False,
    "followup_months": None,
    "trial_duration_months": None,
    "os_median_reached_trt": True,
    "treatment_specific_utilities": None,
    "resubmission": False,
    "prevalence_value": None,
    "prevalence_unit": None,
    "prevalence_kind": None,
    "prevalence_region": None,
    "price_reduction_pct": 21.0,
    "price_reduction_qualifier": "at_least",
    "price_reduction_band": None,
    "price_reduction_status": "pct",
    "wtp_threshold": 50000.0,
    "evidence": [{"field": "agency_icer", "document": "pe", "quote": "ICER of $171,723 per QALY", "page": 3}],
    "notes": "rule 4: point estimate used; range recorded",
}
USAGE = {
    "prompt_tokens": 1000,
    "completion_tokens": 500,
    "cost": 0.0123,
    "prompt_tokens_details": {"cached_tokens": 0},
    "completion_tokens_details": {"reasoning_tokens": 100},
}


class FakePost:
    """Stands in for the HTTP call: records each request body and returns canned responses in turn."""

    def __init__(self, *responses):
        self.bodies, self.responses = [], list(responses) or [ok()]

    def __call__(self, body):
        self.bodies.append(body)
        return self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]


def ok(content=None, finish="stop"):
    content = json.dumps(RECORD) if content is None else content
    return (
        200,
        {
            "id": "gen-1",
            "model": "anthropic/claude-opus-5.5",
            "provider": "Anthropic",
            "usage": USAGE,
            "choices": [{"message": {"content": content}, "finish_reason": finish}],
        },
        {},
    )


def fail(code, error_type=None, status=None):
    meta = {"error_type": error_type} if error_type else {}
    return status or code, {"error": {"code": code, "message": "nope", "metadata": meta}}, {"Retry-After": "0"}


@pytest.fixture
def pages(tmp_path):
    d = tmp_path / "pages"
    (d / "PC0195-000").mkdir(parents=True)
    for kind in ("rec", "pe"):
        (d / "PC0195-000" / f"{kind}.pdf").write_bytes(b"%PDF-1.7 fake")
    return d


def test_schema_accepts_a_full_record_and_rejects_unknown_codes():
    Extraction.model_validate(RECORD)
    with pytest.raises(ValidationError):
        Extraction.model_validate(RECORD | {"ratio_status": "fine"})
    with pytest.raises(ValidationError):
        Extraction.model_validate(RECORD | {"extra_field": 1})


def test_instructions_carry_the_spec_rules():
    assert "Rules for hard cases" in extract.SYSTEM and "PC0195" in extract.SYSTEM
    assert "Computed in code" not in extract.SYSTEM  # §4 is code, not prompt
    assert len(extract.PROMPT_VERSION) == 8


def test_run_writes_one_record_and_skips_it_next_time(tmp_path, pages):
    ex, post, cohort = extract.EXTRACTORS["a"], FakePost(), pd.DataFrame({"project": ["PC0195-000", "SR0001-000"]})
    out = tmp_path / "out"
    summary = extract.run(cohort, ex, pages_dir=pages, out_dir=out, post=post)
    assert summary.status.tolist() == ["ok", "no_pages"]
    record = json.loads(extract.out_path(ex, "PC0195-000", out).read_text())
    assert record["extraction"]["agency_icer"] == 171723.0 and record["error"] is None
    assert record["usage"]["cost_usd"] == 0.0123 and record["provider"] == "Anthropic"
    assert record["documents"] == ["rec", "pe"]

    body = post.bodies[0]
    assert body["model"] == "anthropic/claude-opus-5.5"
    assert body["plugins"] == [{"id": "file-parser", "pdf": {"engine": "native"}}]
    assert body["provider"] == {"require_parameters": True, "order": ["anthropic"], "allow_fallbacks": False}
    assert body["response_format"]["json_schema"]["schema"] == Extraction.model_json_schema()
    content = body["messages"][1]["content"]
    assert [c["type"] for c in content] == ["text", "file", "text", "file", "text"]
    assert content[0]["text"].startswith("Document `rec`") and content[2]["text"].startswith("Document `pe`")
    assert content[1]["file"]["file_data"].startswith("data:application/pdf;base64,")

    again = extract.run(cohort, ex, pages_dir=pages, out_dir=out, post=post)
    assert again.status.tolist() == ["cached", "no_pages"] and len(post.bodies) == 1


def test_extractor_ids_are_safe_folder_names():
    assert "/" not in extract.EXTRACTORS["a"].id and extract.EXTRACTORS["a"].id.endswith(extract.PROMPT_VERSION)


@pytest.mark.parametrize(
    ("post", "error"),
    [
        (FakePost(ok(finish="length")), "length"),
        (FakePost(ok(finish="content_filter")), "content_filter"),
        (FakePost(ok(content='{"sponsor_icer": 1}')), "invalid_output"),
        (FakePost(fail(400, "context_length_exceeded")), "context_length_exceeded"),
        (FakePost(fail(402)), "http_402"),
        (FakePost(fail(502, "provider_unavailable", status=200)), "provider_unavailable"),  # error after headers
    ],
)
def test_failed_calls_are_recorded_and_retried_next_run(tmp_path, pages, post, error, monkeypatch):
    monkeypatch.setattr(extract.time, "sleep", lambda _: None)
    ex, cohort, out = extract.EXTRACTORS["a"], pd.DataFrame({"project": ["PC0195-000"]}), tmp_path / "out"
    assert extract.run(cohort, ex, pages_dir=pages, out_dir=out, post=post).status.tolist()[0].startswith(error)
    assert json.loads(extract.out_path(ex, "PC0195-000", out).read_text())["extraction"] is None
    extract.run(cohort, ex, pages_dir=pages, out_dir=out, post=FakePost())
    assert json.loads(extract.out_path(ex, "PC0195-000", out).read_text())["error"] is None


def test_rate_limits_are_retried_then_succeed(tmp_path, pages, monkeypatch):
    monkeypatch.setattr(extract.time, "sleep", lambda _: None)
    post = FakePost(fail(429, "rate_limit_exceeded"), fail(503), ok())
    ex, cohort = extract.EXTRACTORS["a"], pd.DataFrame({"project": ["PC0195-000"]})
    assert extract.run(cohort, ex, pages_dir=pages, out_dir=tmp_path / "out", post=post).status.tolist() == ["ok"]
    assert len(post.bodies) == 3


def test_api_key_comes_from_env_or_dotenv(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "from-env")
    assert extract.api_key() == "from-env"
    monkeypatch.delenv("OPENROUTER_API_KEY")
    monkeypatch.setattr(extract.config, "ROOT", tmp_path)
    (tmp_path / ".env").write_text("# comment\nOPENROUTER_API_KEY='from-file'\n")
    assert extract.api_key() == "from-file"
