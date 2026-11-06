"""Typed contracts keep uncertain sales signals separate from public evidence."""
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Signal(Record):
    code: Literal["need_fit", "operational_pain", "multiple_sites", "continuous_operations",
                  "senior_role", "referral", "approved_budget", "confirmed_authority", "dated_timeline"]
    quote: str


class Dimension(Record):
    status: Literal["confirmed", "unknown", "negative", "ambiguous"]
    evidence: list[str]
    uncertainty: str
    questions: list[str]


class Lead(Record):
    name: str
    email: str
    title: str
    company: str
    domain: str
    geography: str
    industry: str
    need: str
    referral: str
    knowns: list[str]
    budget: Dimension
    authority: Dimension
    need_dimension: Dimension
    timeline: Dimension
    signals: list[Signal]
    fit: Literal["promising", "unclear", "poor"]
    fit_reason: str


class EvidenceRef(Record):
    source_id: str
    quote: str


class FinancialContext(Record):
    currency: str
    units: str
    reporting_period: str
    publication_date: str
    scope: str


class Claim(Record):
    text: str
    kind: Literal["supplied", "public", "inference", "unknown"]
    evidence: list[EvidenceRef]
    input_quote: str
    uncertainty: str
    financial_context: FinancialContext | None
    event_date: str


class Topic(Record):
    name: Literal["Organisation and reporting lines", "Budget and investment signals",
                  "News and strategic announcements", "Investor priorities",
                  "Corporate changes and customer relationships"]
    claims: list[Claim]
    gaps: list[str]


class Research(Record):
    topics: list[Topic]
    positioning: list[Claim]
    stakeholder_hypothesis: list[Claim]
    conflicts: list[str]


class AccountAdvice(Record):
    positioning: list[Claim]
    stakeholder_hypothesis: list[Claim]
    conflicts: list[str]


class MatchDimension(Record):
    dimension: Literal["industry", "use_case", "operating_context", "geography", "referral", "same_company"]
    matched: bool
    rationale: Claim


class Material(Record):
    title: str
    source_id: str
    dimensions: list[MatchDimension]
    relevance: Claim
    limitations: list[str]
    own_company_expansion_assessment: str


class Materials(Record):
    candidates: list[Material]
    referral_findings: list[Claim]
    gaps: list[str]


class MaterialChoice(Record):
    """Small AI advisory judgement over source-extracted case-study candidates.

    Full citation-rich Materials records are built locally from inspected
    originals, not re-generated as a large deeply nested model response.
    """
    preferred_source_id: str
    ranked_source_ids: list[str]
    rationale: str
    gaps: list[str]


class Partner(Record):
    name: str
    partner_type: str
    ecosystem_evidence: Claim
    capabilities: list[Claim]
    geographic_coverage: Claim
    availability: str
    limitations: list[str]


class Routing(Record):
    recommended_motion: Literal["direct_ae", "partner_led"]
    rationale: list[Claim]
    candidates: list[Partner]
    proposed_partner_name: str
    required_partner_type: str
    commercial_owner: str
    implementation_owner: str
    next_action: str
    gaps: list[str]


class RouteAdvice(Record):
    """Tiny AI advisory schema, avoiding large nested partner-coverage JSON.

    All candidate facts and geographic/capability gates remain sourced locally.
    """
    recommended_motion: Literal["direct_ae", "partner_led"]
    proposed_partner_name: str
    reason: str
    next_action: str
    gaps: list[str]


class EmailDraft(Record):
    branch: Literal["initial", "no_reply", "interested", "budget_clarification", "stakeholder_referral"]
    subject: str
    paragraphs: list[Claim]
    trigger: str
    why_this_message: str
    if_buyer_responds: str
    hypothetical: bool


class Responses(Record):
    drafts: list[EmailDraft]
    limitations: list[str]


class AuditFinding(Record):
    path: str
    reason: str
    severity: Literal["warning", "error"]


class Audit(Record):
    findings: list[AuditFinding]


class Source(Record):
    source_id: str
    url: str
    title: str
    title_basis: str = "legacy registry label; original title provenance not separately recorded"
    retrieved_at: str
    publication_date: str = ""
    publication_date_basis: str = "not available"
    access: Literal["inspected_page", "inspected_pdf", "search_summary_only", "search_excerpt_only", "inaccessible"] = "search_summary_only"
    inspection_method: str = "not inspected"
    text: str = ""
    search_context: str = ""
    truncated: bool = False
    pages_read: int = 0
    pages_total: int = 0
    pages_retained: list[int] = Field(default_factory=list)
    error: str = ""
    queries: list[str] = Field(default_factory=list)
    cited_by: list[dict[str, Any]] = Field(default_factory=list)


STAGE_NAMES = ["Qualification", "Deep Account Research", "Response Generation",
               "Case Study and Material Matching", "Partner Identification", "AE Handoff Summary"]


class Stage(Record):
    name: str
    status: Literal["pending", "running", "complete", "partial", "failed", "skipped"] = "pending"
    started_at: str = ""
    finished_at: str = ""
    elapsed_seconds: float = 0
    output: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    execution_origin: str = "not executed"
    technical_status: Literal["not_run", "succeeded", "partial", "failed", "skipped"] = "not_run"
    evidence_status: Literal["not_assessed", "supported", "partial"] = "not_assessed"


class Run(Record):
    run_id: str
    mode: Literal["live", "offline_test"]
    started_at: str
    finished_at: str = ""
    as_of_date: str
    input: str
    config: dict[str, Any]
    status: Literal["running", "complete", "partial", "failed"] = "running"
    stages: list[Stage] = Field(default_factory=lambda: [Stage(name=n) for n in STAGE_NAMES])
    sources: dict[str, Source] = Field(default_factory=dict)
    queries: dict[str, list[str]] = Field(default_factory=dict)
    usage: list[dict[str, Any]] = Field(default_factory=list)
    logs: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    retrieval_cache: dict[str, Any] = Field(default_factory=dict)
    followup_updates: list[dict[str, Any]] = Field(default_factory=list)
