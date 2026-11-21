"""The extraction output, as specified in docs/extraction-spec.md §2.

Fields are extracted in four calls, one per group of related fields (`GROUPS`): the ICERs with costs and QALYs,
the agency's stepwise changes, the submission features, and the price reduction. Each call returns its group's
fields plus `evidence` and `notes`; the four are merged into one `Extraction` per review. Grouping keeps each call
focused, and keeps each schema within Anthropic's limit of 16 fields that may be null or of several types.

Each field's description is sent to the model as part of the JSON schema, so it states the field briefly and
points to the spec's rule numbers; the rules themselves are in the prompt. Values computed in code (the ratio,
the outcomes, `rare_disease`, ...) are not here: see spec §4.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

IcerStatus = Literal["point", "dominant", "dominated", "redacted", "range_only", "not_reported"]
AgencyIcerStatus = Literal[
    "point", "dominant", "dominated", "redacted", "range_only", "not_reported", "no_reanalysis", "lower_bound"
]
RatioStatus = Literal[
    "ok",
    "sponsor_dominant",
    "agency_dominant",
    "no_reanalysis",
    "range_only",
    "comparator_mismatch",
    "redacted",
    "not_cost_utility",
    "not_reported",
]
StepCategory = Literal[
    "extrapolation_survival",
    "treatment_effect_waning",
    "utilities",
    "time_horizon",
    "comparator",
    "drug_costs_wastage_dosing",
    "treatment_duration",
    "other_costs",
    "population",
    "model_structure_error",
    "other",
]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Evidence(_Strict):
    field: str = Field(description="Name of the field this quote supports")
    document: Literal["rec", "pe", "clin"] = Field(
        description="Which attached document: rec (Recommendation), pe (economic report), clin (clinical report)"
    )
    quote: str = Field(description="Verbatim text from that document, 30 words or fewer")
    page: int = Field(description="Page number within that attached document (1 = its first page)")


class Step(_Strict):
    order: int = Field(description="Position in the agency's stepwise table, from 1")
    description: str = Field(description="What the agency changed, 15 words or fewer")
    category: StepCategory
    icer_after: float | None = Field(description="ICER ($/QALY) after this step; null if not reported or dominant")


class IcerFields(_Strict):
    """Spec §2.1 the two ICERs, and §2.2 costs and QALYs."""

    sponsor_icer: float | None = Field(description="Sponsor's base-case ICER, $/QALY (rule 5)")
    sponsor_icer_status: IcerStatus
    agency_icer: float | None = Field(description="CDA-AMC base-case ICER, $/QALY; point estimate over range (rule 4)")
    agency_icer_status: AgencyIcerStatus
    agency_icer_range_low: float | None = Field(description="Lower end of the agency's range, if it gives one")
    agency_icer_range_high: float | None = Field(description="Upper end of the agency's range, if it gives one")
    agency_icer_headline: float | None = Field(
        description="The figure the Recommendation leads with, only if it differs from agency_icer"
    )
    comparator: str | None = Field(description="The one comparator both ICERs refer to (rule 1)")
    icer_type: Literal["probabilistic", "deterministic"] | None = Field(description="Rule 2")
    icer_type_mismatch: bool = Field(description="Sponsor and agency figures are of different types (rule 3)")
    icer_basis: Literal["pairwise", "sequential"] | None = Field(description="Rule 7")
    sponsor_version: Literal["original", "revised"] | None = Field(description="Rule 5")
    analysis_type: Literal["cost_utility", "cost_minimization", "cost_comparison", "none", "unclear"]
    ratio_status: RatioStatus = Field(description="'ok' only if both ICERs are usable point estimates (rules 4, 8, 9)")

    # costs and QALYs, same comparator as the ICERs
    inc_cost_sponsor: float | None = Field(description="Sponsor's incremental cost, $")
    inc_qaly_sponsor: float | None = Field(description="Sponsor's incremental QALYs")
    inc_cost_agency: float | None = Field(description="Agency's incremental cost, $")
    inc_qaly_agency: float | None = Field(description="Agency's incremental QALYs")
    inc_derived: bool = Field(description="True if computed from totals rather than stated")


class StepwiseFields(_Strict):
    """Spec §2.3 the agency's stepwise changes. They describe the critique and are never model inputs."""

    has_stepwise_table: bool = Field(description="The agency reports an ICER after each change")
    stepwise_type: Literal["cumulative", "individual"] | None
    steps: list[Step] = Field(description="Rows of the stepwise table, in order; empty if there is none")


class FeatureFields(_Strict):
    """Spec §2.4 submission features: only what the sponsor knew at submission, never the agency's judgement."""

    pivotal_design: Literal["rct_h2h", "rct_placebo_or_other", "single_arm", "observational", "mixed", "unclear"]
    comparison_method: Literal["direct", "itc_nma", "naive", "assumption", "unclear"] = Field(
        description="For the primary comparator only; an NMA run but not used in the model is 'naive'"
    )
    primary_endpoint_type: Literal[
        "os", "pfs_or_efs", "response_or_surrogate", "clinical_scale", "other", "unclear"
    ] = Field(description="Co-primary OS + PFS is 'os'; response indices (IGA, HiSCR, SRI) are 'clinical_scale'")
    comparator_type: Literal["active_drug", "bsc_or_no_treatment", "mixed_basket", "unclear"]
    n_comparators_sponsor: int | None
    model_type: Literal[
        "partitioned_survival", "markov_or_state_transition", "decision_tree", "microsimulation", "other", "unclear"
    ]
    time_horizon_years: float | None = Field(description="Null for 'lifetime' with no years stated")
    lifetime_unspecified: bool = Field(description="Time horizon is 'lifetime' with no years stated")
    followup_months: float | None = Field(description="Median follow-up of the data cut used in the model")
    trial_duration_months: float | None = Field(description="Planned trial duration, if stated")
    os_median_reached_trt: bool | None = Field(description="Oncology only; null otherwise")
    treatment_specific_utilities: bool | None = Field(description="Only if stated explicitly")
    resubmission: bool | None = Field(description="Same drug and indication reviewed before; reconsideration is not")
    prevalence_value: float | None = Field(description="As stated, before any conversion")
    prevalence_unit: Literal["per_100k", "per_10k", "per_million", "percent", "one_in_n", "patients"] | None
    prevalence_kind: Literal["prevalence", "incidence", "eligible_patients"] | None
    prevalence_region: Literal["canada", "other", "not_stated"] | None


class PriceFields(_Strict):
    """Spec §2.5 the price reduction."""

    price_reduction_pct: float | None = Field(description="% cut needed to reach the threshold; lower end of a range")
    price_reduction_qualifier: Literal["exact", "at_least", "greater_than", "approximately", "range"] | None
    price_reduction_band: str | None = Field(description="The band label, if the review gives one")
    price_reduction_status: Literal["pct", "band", "not_needed", "no_pct_specified", "not_achievable", "not_reported"]
    wtp_threshold: float | None = Field(description="Willingness-to-pay threshold, $/QALY; usually 50000")


class _Audit(_Strict):
    """Spec §2.6: returned by every call."""

    evidence: list[Evidence] = Field(description="Up to 4 quotes, for the fields of this call that are not obvious")
    notes: str = Field(description="Judgement calls, with the rule number; populations or comparators not used")


class IcerCall(IcerFields, _Audit):
    pass


class StepwiseCall(StepwiseFields, _Audit):
    pass


class FeatureCall(FeatureFields, _Audit):
    pass


class PriceCall(PriceFields, _Audit):
    pass


GROUPS: dict[str, type[_Audit]] = {
    "icers": IcerCall,
    "stepwise": StepwiseCall,
    "features": FeatureCall,
    "price": PriceCall,
}


class Extraction(IcerFields, StepwiseFields, FeatureFields, PriceFields, _Audit):
    """One review's merged record: every group's fields, all evidence, and the notes of each call."""


def merge(parts: dict[str, _Audit]) -> Extraction:
    """Combine one validated output per group into the review's record."""
    fields, evidence, notes = {}, [], []
    for name, part in parts.items():
        data = part.model_dump()
        evidence += data.pop("evidence")
        if note := data.pop("notes").strip():
            notes.append(f"{name}: {note}")
        fields |= data
    return Extraction.model_validate(fields | {"evidence": evidence, "notes": "\n".join(notes)})
