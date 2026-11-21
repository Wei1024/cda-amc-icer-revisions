"""The extraction runner, with a fake client: no API calls."""

import json
from types import SimpleNamespace

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
    "evidence": [{"field": "agency_icer", "quote": "ICER of $171,723 per QALY", "page": 3}],
    "notes": "rule 4: point estimate used; range recorded",
}
USAGE = SimpleNamespace(input_tokens=1000, output_tokens=500, cache_read_input_tokens=0, cache_creation_input_tokens=0)


class FakeClient:
    """Stands in for anthropic.Anthropic: records each call and returns a canned response."""

    def __init__(self, stop_reason="end_turn", parsed=RECORD, raises=None):
        self.calls, self.stop_reason, self.parsed, self.raises = [], stop_reason, parsed, raises
        self.messages = self

    def with_options(self, **_):
        return self

    def parse(self, **kwargs):
        self.calls.append(kwargs)
        response = SimpleNamespace(
            model=kwargs["model"], _request_id="req_1", stop_reason=self.stop_reason, usage=USAGE
        )
        if self.raises:
            raise self.raises
        response.parsed_output = None if self.parsed is None else Extraction.model_validate(self.parsed)
        return response


@pytest.fixture
def pages(tmp_path):
    d = tmp_path / "pages"
    d.mkdir()
    (d / "PC0195-000.pdf").write_bytes(b"%PDF-1.7 fake")
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
    ex, client, cohort = extract.EXTRACTORS["a"], FakeClient(), pd.DataFrame({"project": ["PC0195-000", "SR0001-000"]})
    out = tmp_path / "out"
    summary = extract.run(cohort, ex, pages_dir=pages, out_dir=out, client=client)
    assert summary.status.tolist() == ["ok", "no_pages"]
    record = json.loads(extract.out_path(ex, "PC0195-000", out).read_text())
    assert record["extraction"]["agency_icer"] == 171723.0 and record["error"] is None
    assert record["cost_usd"] == pytest.approx((1000 * 4 + 500 * 20) / 1e6)
    call = client.calls[0]
    assert call["model"] == "claude-opus-5-5" and call["output_format"] is Extraction
    assert call["messages"][0]["content"][0]["type"] == "document"

    again = extract.run(cohort, ex, pages_dir=pages, out_dir=out, client=client)
    assert again.status.tolist() == ["cached", "no_pages"] and len(client.calls) == 1


@pytest.mark.parametrize(
    ("client", "error"),
    [
        (FakeClient(stop_reason="max_tokens"), "max_tokens"),
        (FakeClient(stop_reason="refusal"), "refusal"),
        (FakeClient(parsed=None), "no_output"),
    ],
)
def test_failed_calls_are_recorded_and_retried_next_run(tmp_path, pages, client, error):
    ex, cohort, out = extract.EXTRACTORS["a"], pd.DataFrame({"project": ["PC0195-000"]}), tmp_path / "out"
    assert extract.run(cohort, ex, pages_dir=pages, out_dir=out, client=client).status.tolist() == [error]
    assert json.loads(extract.out_path(ex, "PC0195-000", out).read_text())["extraction"] is None
    extract.run(cohort, ex, pages_dir=pages, out_dir=out, client=FakeClient())
    assert json.loads(extract.out_path(ex, "PC0195-000", out).read_text())["error"] is None
