"""The extraction runner, with a fake client: no API calls."""

import json

import pandas as pd
import pytest
from pydantic import ValidationError

from icer_revisions import extract
from icer_revisions.schema import GROUPS, Extraction

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


def group_of(body):
    return body["response_format"]["json_schema"]["name"].removeprefix("extraction_")


def ok(group, content=None, finish="stop"):
    """A successful response for one group's call, holding that group's fields of RECORD."""
    if content is None:
        fields = {k: RECORD[k] for k in GROUPS[group].model_fields if k not in ("evidence", "notes")}
        content = json.dumps(
            fields | {"evidence": RECORD["evidence"] if group == "icers" else [], "notes": f"{group} note"}
        )
    return (
        200,
        {
            "id": f"gen-{group}",
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


class FakePost:
    """Stands in for the HTTP call: answers each group's call, with scripted responses for chosen groups."""

    def __init__(self, **scripted):  # group -> list of responses, used in turn
        self.bodies, self.scripted = [], {g: list(r) for g, r in scripted.items()}

    def __call__(self, body):
        self.bodies.append(body)
        group = group_of(body)
        queue = self.scripted.get(group)
        return queue.pop(0) if queue else ok(group)


@pytest.fixture
def pages(tmp_path):
    d = tmp_path / "pages"
    (d / "PC0195-000").mkdir(parents=True)
    for kind in ("rec", "pe"):
        (d / "PC0195-000" / f"{kind}.pdf").write_bytes(b"%PDF-1.7 fake")
    return d


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr(extract.time, "sleep", lambda _: None)


def test_schema_accepts_a_full_record_and_rejects_unknown_codes():
    Extraction.model_validate(RECORD)
    with pytest.raises(ValidationError):
        Extraction.model_validate(RECORD | {"ratio_status": "fine"})
    with pytest.raises(ValidationError):
        Extraction.model_validate(RECORD | {"extra_field": 1})


def test_groups_cover_every_field_once():
    fields = [f for m in GROUPS.values() for f in m.model_fields if f not in ("evidence", "notes")]
    assert sorted(fields) == sorted(f for f in Extraction.model_fields if f not in ("evidence", "notes"))


def test_instructions_carry_the_spec_rules():
    assert "Rules for hard cases" in extract.SYSTEM and "PC0195" in extract.SYSTEM
    assert "Computed in code" not in extract.SYSTEM  # §4 is code, not prompt
    assert len(extract.PROMPT_VERSION) == 8


def test_run_makes_one_call_per_group_with_a_shared_cached_prefix(tmp_path, pages):
    ex, post, cohort = extract.EXTRACTORS["a"], FakePost(), pd.DataFrame({"project": ["PC0195-000", "SR0001-000"]})
    out = tmp_path / "out"
    summary = extract.run(cohort, ex, pages_dir=pages, out_dir=out, post=post)
    assert summary.status.tolist() == ["ok", "no_pages"]
    record = json.loads(extract.out_path(ex, "PC0195-000", out).read_text())
    assert record["error"] is None and record["documents"] == ["rec", "pe"]
    assert record["extraction"]["agency_icer"] == 171723.0 and record["extraction"]["wtp_threshold"] == 50000.0
    assert record["extraction"]["notes"].splitlines() == [f"{g}: {g} note" for g in GROUPS]
    assert record["cost_usd"] == pytest.approx(4 * 0.0123) and record["calls"]["price"]["provider"] == "Anthropic"

    assert [group_of(b) for b in post.bodies] == list(GROUPS)
    first = post.bodies[0]
    assert first["model"] == "anthropic/claude-opus-5.5"
    assert first["plugins"] == [{"id": "file-parser", "pdf": {"engine": "native"}}]
    assert first["provider"] == {"require_parameters": True, "order": ["anthropic"], "allow_fallbacks": False}
    content = first["messages"][1]["content"]
    assert [c["type"] for c in content] == ["text", "file", "text", "file", "text", "text"]
    assert content[0]["text"].startswith("Document `rec`") and content[2]["text"].startswith("Document `pe`")
    assert content[4]["cache_control"] == {"type": "ephemeral"}  # breakpoint right after the last PDF
    # every call shares the same system message and documents; only the last line differs
    for b in post.bodies[1:]:
        assert b["messages"][0] == first["messages"][0] and b["messages"][1]["content"][:-1] == content[:-1]
    assert len({b["messages"][1]["content"][-1]["text"] for b in post.bodies}) == 4

    again = extract.run(cohort, ex, pages_dir=pages, out_dir=out, post=post)
    assert again.status.tolist() == ["cached", "no_pages"] and len(post.bodies) == 4


def test_extractor_ids_are_safe_folder_names():
    assert "/" not in extract.EXTRACTORS["a"].id and extract.EXTRACTORS["a"].id.endswith(extract.PROMPT_VERSION)


@pytest.mark.parametrize(
    ("response", "error"),
    [
        (ok("features", finish="length"), "features: length"),
        (ok("features", finish="content_filter"), "features: content_filter"),
        (ok("features", content='{"pivotal_design": "rct_h2h"}'), "features: invalid_output"),
        (fail(400, "context_length_exceeded"), "features: context_length_exceeded"),
        (fail(402), "features: http_402"),
        (fail(502, "provider_unavailable", status=200), "features: provider_unavailable"),  # error after headers
    ],
)
def test_a_failed_group_is_recorded_and_only_it_is_retried(tmp_path, pages, response, error):
    ex, cohort, out = extract.EXTRACTORS["a"], pd.DataFrame({"project": ["PC0195-000"]}), tmp_path / "out"
    post = FakePost(features=[response] * 4)  # enough to outlast the retries
    assert extract.run(cohort, ex, pages_dir=pages, out_dir=out, post=post).status.tolist()[0].startswith(error)
    record = json.loads(extract.out_path(ex, "PC0195-000", out).read_text())
    assert record["extraction"] is None and record["calls"]["icers"]["error"] is None

    retry = FakePost()
    extract.run(cohort, ex, pages_dir=pages, out_dir=out, post=retry)
    assert [group_of(b) for b in retry.bodies] == ["features"]
    assert json.loads(extract.out_path(ex, "PC0195-000", out).read_text())["error"] is None


def test_rate_limits_are_retried_then_succeed(tmp_path, pages):
    post = FakePost(icers=[fail(429, "rate_limit_exceeded"), fail(503)])
    ex, cohort = extract.EXTRACTORS["a"], pd.DataFrame({"project": ["PC0195-000"]})
    assert extract.run(cohort, ex, pages_dir=pages, out_dir=tmp_path / "out", post=post).status.tolist() == ["ok"]
    assert [group_of(b) for b in post.bodies] == ["icers", "icers", "icers", "stepwise", "features", "price"]


def test_api_key_comes_from_env_or_dotenv(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "from-env")
    assert extract.api_key() == "from-env"
    monkeypatch.delenv("OPENROUTER_API_KEY")
    monkeypatch.setattr(extract.config, "ROOT", tmp_path)
    (tmp_path / ".env").write_text("# comment\nOPENROUTER_API_KEY='from-file'\n")
    assert extract.api_key() == "from-file"
