# analytics/opportunity.py
"""
Opportunity analysis layer for the AI Director.

Responsibilities:
- evaluate a YouTube opportunity from available evidence;
- combine demand, dynamics, competition, applicability and constraints;
- identify strengths, risks and missing evidence;
- estimate opportunity quality and confidence;
- prepare a compact structured payload for Director.

This module does NOT:
- search YouTube;
- call MCP;
- call an AI provider;
- create recommendations;
- make the final strategic decision.

It answers only:

    "What does the available evidence say about this opportunity?"

Director decides:

    "What should we do about it?"
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from math import log1p
from typing import Any, Iterable, Mapping, Sequence


# ============================================================
# CONSTANTS
# ============================================================

EPSILON = 1e-9

MIN_SAMPLE_FOR_CONFIDENCE = 10

# Weights intentionally describe analytical dimensions,
# not a strategic decision.
DEMAND_WEIGHT = 0.25
DYNAMICS_WEIGHT = 0.25
COMPETITION_WEIGHT = 0.20
APPLICABILITY_WEIGHT = 0.20
EVIDENCE_WEIGHT = 0.10

DEFAULT_THRESHOLD = 0.50

MAX_EVIDENCE_ITEMS = 20
MAX_RISK_ITEMS = 20
MAX_CONSTRAINT_ITEMS = 20
MAX_MISSING_ITEMS = 20


# ============================================================
# DATA CLASSES
# ============================================================

@dataclass(slots=True)
class OpportunityDimension:
    """
    One analytical dimension of an opportunity.

    score:
        0..1, where higher means stronger evidence.

    confidence:
        0..1, describing how trustworthy the available evidence is.

    This is not a strategic recommendation.
    """

    name: str

    score: float = 0.0
    confidence: float = 0.0

    evidence: list[str] = field(
        default_factory=list
    )

    risks: list[str] = field(
        default_factory=list
    )

    missing_data: list[str] = field(
        default_factory=list
    )


@dataclass(slots=True)
class OpportunityAssessment:
    """
    Complete analytical assessment of one opportunity.
    """

    opportunity_id: str | None = None

    title: str = ""
    description: str = ""

    overall_score: float = 0.0
    confidence: float = 0.0

    dimensions: dict[
        str,
        OpportunityDimension,
    ] = field(
        default_factory=dict
    )

    strengths: list[str] = field(
        default_factory=list
    )

    risks: list[str] = field(
        default_factory=list
    )

    constraints: list[str] = field(
        default_factory=list
    )

    missing_data: list[str] = field(
        default_factory=list
    )

    evidence: list[str] = field(
        default_factory=list
    )

    signals: list[str] = field(
        default_factory=list
    )

    applicability: dict[str, Any] = field(
        default_factory=dict
    )

    competition: dict[str, Any] = field(
        default_factory=dict
    )

    trend: dict[str, Any] = field(
        default_factory=dict
    )

    metadata: dict[str, Any] = field(
        default_factory=dict
    )


# ============================================================
# BASIC HELPERS
# ============================================================

def _safe_float(
    value: Any,
    default: float = 0.0,
) -> float:
    try:
        if value is None:
            return default

        result = float(value)

        if result != result:
            return default

        return result

    except (TypeError, ValueError):
        return default


def _safe_int(
    value: Any,
    default: int = 0,
) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _text(
    value: Any,
) -> str:
    if value is None:
        return ""

    return str(value).strip()


def _clamp(
    value: float,
    minimum: float = 0.0,
    maximum: float = 1.0,
) -> float:
    return max(
        minimum,
        min(maximum, value),
    )


def _mean(
    values: Iterable[float],
) -> float:
    values = list(values)

    if not values:
        return 0.0

    return sum(values) / len(values)


def _get(
    data: Mapping[str, Any],
    *keys: str,
    default: Any = None,
) -> Any:
    for key in keys:
        if key in data:
            value = data[key]

            if value is not None:
                return value

    return default


def _as_list(
    value: Any,
) -> list[Any]:
    if value is None:
        return []

    if isinstance(
        value,
        str,
    ):
        return [
            value
        ] if value.strip() else []

    if isinstance(
        value,
        Sequence,
    ):
        return list(value)

    return [value]


def _unique_strings(
    values: Iterable[Any],
) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()

    for value in values:
        text = _text(value)

        if not text:
            continue

        if text in seen:
            continue

        seen.add(text)
        result.append(text)

    return result


def _log_normalize(
    value: float,
    reference: float,
) -> float:
    value = max(
        0.0,
        _safe_float(value),
    )

    reference = max(
        0.0,
        _safe_float(reference),
    )

    if value <= 0:
        return 0.0

    if reference <= 0:
        return 0.0

    return _clamp(
        log1p(value)
        / log1p(reference)
    )


# ============================================================
# EVIDENCE EXTRACTION
# ============================================================

def _extract_metrics(
    analytics: Mapping[str, Any]
    | None,
) -> Mapping[str, Any]:
    if not analytics:
        return {}

    metrics = _get(
        analytics,
        "metrics",
        default={},
    )

    if isinstance(
        metrics,
        Mapping,
    ):
        return metrics

    return analytics


def _extract_trend(
    trend: Mapping[str, Any]
    | None,
) -> Mapping[str, Any]:
    if not trend:
        return {}

    return trend


# ============================================================
# DEMAND
# ============================================================

def assess_demand(
    analytics: Mapping[str, Any]
    | None = None,
    *,
    videos: Sequence[
        Mapping[str, Any]
    ] | None = None,
    demand_data: Mapping[str, Any]
    | None = None,
) -> OpportunityDimension:
    """
    Estimate demand from observable audience response.

    Possible evidence:
    - average views;
    - median views;
    - total views;
    - engagement;
    - sample size;
    - explicit demand metrics if available.

    This intentionally does not infer demand from a single
    viral video.
    """

    analytics = analytics or {}
    demand_data = demand_data or {}

    metrics = _extract_metrics(
        analytics
    )

    videos = list(
        videos or []
    )

    average_views = _safe_float(
        _get(
            demand_data,
            "average_views",
            default=_get(
                metrics,
                "average_views",
                default=0,
            ),
        )
    )

    median_views = _safe_float(
        _get(
            demand_data,
            "median_views",
            default=_get(
                metrics,
                "median_views",
                default=0,
            ),
        )
    )

    total_views = _safe_float(
        _get(
            demand_data,
            "total_views",
            default=_get(
                metrics,
                "total_views",
                default=0,
            ),
        )
    )

    engagement = _safe_float(
        _get(
            demand_data,
            "engagement_rate",
            default=_get(
                metrics,
                "average_engagement_rate",
                "engagement_rate",
                default=0,
            ),
        )
    )

    sample_size = _safe_int(
        _get(
            demand_data,
            "sample_size",
            default=_get(
                metrics,
                "count",
                default=len(videos),
            ),
        )
    )

    # Explicit normalized demand score can be supplied
    # by another analytical source.
    explicit_score = _get(
        demand_data,
        "score",
        "demand_score",
    )

    if explicit_score is not None:
        score = _clamp(
            _safe_float(
                explicit_score
            )
        )
    else:
        # Components are relative signals.
        view_signal = _clamp(
            _log_normalize(
                average_views,
                max(
                    average_views,
                    median_views,
                    1.0,
                )
            )
        )

        median_signal = _clamp(
            _log_normalize(
                median_views,
                max(
                    average_views,
                    median_views,
                    1.0,
                )
            )
        )

        engagement_signal = _clamp(
            engagement * 20.0
        )

        sample_signal = _clamp(
            sample_size
            / 30.0
        )

        score = _clamp(
            0.35 * view_signal
            + 0.25 * median_signal
            + 0.25 * engagement_signal
            + 0.15 * sample_signal
        )

    evidence: list[str] = []

    if average_views > 0:
        evidence.append(
            f"Average observed views: {average_views:.0f}."
        )

    if median_views > 0:
        evidence.append(
            f"Median observed views: {median_views:.0f}."
        )

    if total_views > 0:
        evidence.append(
            f"Total observed views: {total_views:.0f}."
        )

    if engagement > 0:
        evidence.append(
            f"Average engagement rate: {engagement:.4f}."
        )

    if sample_size > 0:
        evidence.append(
            f"Observed sample size: {sample_size}."
        )

    risks: list[str] = []
    missing: list[str] = []

    if sample_size < 5:
        risks.append(
            "Demand evidence is based on a very small sample."
        )

    if sample_size < MIN_SAMPLE_FOR_CONFIDENCE:
        missing.append(
            "More observations are needed to validate demand."
        )

    if median_views <= 0:
        missing.append(
            "Median view data is unavailable."
        )

    confidence = _clamp(
        0.40 * _clamp(
            sample_size / 30.0
        )
        + 0.30 * (
            1.0
            if average_views > 0
            else 0.0
        )
        + 0.20 * (
            1.0
            if median_views > 0
            else 0.0
        )
        + 0.10 * (
            1.0
            if engagement > 0
            else 0.0
        )
    )

    return OpportunityDimension(
        name="demand",
        score=score,
        confidence=confidence,
        evidence=evidence,
        risks=risks,
        missing_data=missing,
    )


# ============================================================
# DYNAMICS
# ============================================================

def assess_dynamics(
    trend: Mapping[str, Any]
    | None = None,
) -> OpportunityDimension:
    """
    Evaluate whether the opportunity is moving positively,
    negatively or staying stable.
    """

    trend = _extract_trend(
        trend
    )

    explicit_score = _get(
        trend,
        "score",
        "trend_score",
    )

    direction = _text(
        _get(
            trend,
            "direction",
            default="unknown",
        )
    ).lower()

    strength = _clamp(
        _safe_float(
            _get(
                trend,
                "strength",
                default=0,
            )
        )
    )

    confidence = _clamp(
        _safe_float(
            _get(
                trend,
                "confidence",
                default=0,
            )
        )
    )

    if explicit_score is not None:
        score = _clamp(
            _safe_float(
                explicit_score
            )
        )
    else:
        direction_scores = {
            "strong_up": 1.0,
            "up": 0.80,
            "slight_up": 0.65,
            "stable": 0.50,
            "slight_down": 0.35,
            "down": 0.20,
            "strong_down": 0.05,
            "unknown": 0.30,
        }

        base = direction_scores.get(
            direction,
            0.30,
        )

        score = _clamp(
            0.60 * base
            + 0.40 * strength
        )

    evidence: list[str] = []
    risks: list[str] = []
    missing: list[str] = []

    if direction:
        evidence.append(
            f"Observed trend direction: {direction}."
        )

    if strength > 0:
        evidence.append(
            f"Trend strength: {strength:.2f}."
        )

    if confidence > 0:
        evidence.append(
            f"Trend confidence: {confidence:.2f}."
        )

    if direction in {
        "strong_up",
        "up",
        "slight_up",
    }:
        evidence.append(
            "Current dynamics provide positive evidence."
        )

    if direction in {
        "strong_down",
        "down",
        "slight_down",
    }:
        risks.append(
            "Observed dynamics are weakening."
        )

    if direction in {
        "",
        "unknown",
    }:
        missing.append(
            "Reliable comparison period is unavailable."
        )

    return OpportunityDimension(
        name="dynamics",
        score=score,
        confidence=confidence,
        evidence=evidence,
        risks=risks,
        missing_data=missing,
    )


# ============================================================
# COMPETITION
# ============================================================

def assess_competition(
    competition_data: Mapping[str, Any]
    | None = None,
    *,
    videos: Sequence[
        Mapping[str, Any]
    ] | None = None,
) -> OpportunityDimension:
    """
    Evaluate competition.

    Important:
        High competition is not automatically "bad".
        The analytical layer only describes the observed
        competitive environment.

    The score means:
        "how favorable the competitive environment appears
         from the supplied evidence"

    It does not mean:
        "this opportunity should or should not be pursued."
    """

    competition_data = (
        competition_data or {}
    )

    videos = list(
        videos or []
    )

    explicit_score = _get(
        competition_data,
        "score",
        "competition_score",
        "opportunity_score",
    )

    competition_level = _text(
        _get(
            competition_data,
            "level",
            "competition_level",
            default="",
        )
    ).lower()

    competitor_count = _safe_int(
        _get(
            competition_data,
            "competitor_count",
            "channels",
            "unique_channels",
            default=0,
        )
    )

    top_channel_share = _clamp(
        _safe_float(
            _get(
                competition_data,
                "top_channel_share",
                default=0,
            )
        )
    )

    concentration = _clamp(
        _safe_float(
            _get(
                competition_data,
                "concentration",
                default=0,
            )
        )
    )

    if explicit_score is not None:
        score = _clamp(
            _safe_float(
                explicit_score
            )
        )
    else:
        # We intentionally interpret competition as a
        # multidimensional environment.
        #
        # More competitors -> more pressure.
        # High concentration -> less room for a new entrant.
        # But neither is treated as an absolute blocker.
        competitor_pressure = _clamp(
            competitor_count / 50.0
        )

        concentration_pressure = (
            top_channel_share
            if top_channel_share > 0
            else concentration
        )

        if competition_level == "low":
            base = 0.80
        elif competition_level == "medium":
            base = 0.55
        elif competition_level == "high":
            base = 0.30
        elif competition_level == "very_high":
            base = 0.15
        else:
            base = 0.50

        score = _clamp(
            0.60 * base
            + 0.25 * (
                1.0
                - competitor_pressure
            )
            + 0.15 * (
                1.0
                - concentration_pressure
            )
        )

    evidence: list[str] = []
    risks: list[str] = []
    missing: list[str] = []

    if competition_level:
        evidence.append(
            f"Observed competition level: {competition_level}."
        )

    if competitor_count > 0:
        evidence.append(
            f"Observed competitors/channels: {competitor_count}."
        )

    if top_channel_share > 0:
        evidence.append(
            f"Top-channel concentration: {top_channel_share:.2f}."
        )

    if not competition_level:
        missing.append(
            "Competitive intensity classification is unavailable."
        )

    if competitor_count <= 0:
        missing.append(
            "Reliable competitor count is unavailable."
        )

    if competition_level in {
        "high",
        "very_high",
    }:
        risks.append(
            "The observed competitive environment is dense."
        )

    confidence = _clamp(
        0.35 * (
            1.0
            if competition_level
            else 0.0
        )
        + 0.30 * _clamp(
            competitor_count / 20.0
        )
        + 0.20 * (
            1.0
            if (
                top_channel_share > 0
                or concentration > 0
            )
            else 0.0
        )
        + 0.15 * (
            1.0
            if videos
            else 0.0
        )
    )

    return OpportunityDimension(
        name="competition",
        score=score,
        confidence=confidence,
        evidence=evidence,
        risks=risks,
        missing_data=missing,
    )


# ============================================================
# APPLICABILITY
# ============================================================

def assess_applicability(
    applicability_data: Mapping[str, Any]
    | None = None,
    *,
    constraints: Sequence[str]
    | None = None,
) -> OpportunityDimension:
    """
    Evaluate whether the opportunity can realistically fit
    the project's known capabilities and constraints.

    Applicability is not "should we do it".
    It describes compatibility with the project.
    """

    applicability_data = (
        applicability_data or {}
    )

    constraints = _unique_strings(
        constraints or []
    )

    explicit_score = _get(
        applicability_data,
        "score",
        "applicability_score",
        "fit_score",
    )

    fit_level = _text(
        _get(
            applicability_data,
            "level",
            "fit",
            "applicability",
            default="",
        )
    ).lower()

    required_resources = _unique_strings(
        _as_list(
            _get(
                applicability_data,
                "required_resources",
                default=[],
            )
        )
    )

    available_resources = _unique_strings(
        _as_list(
            _get(
                applicability_data,
                "available_resources",
                default=[],
            )
        )
    )

    blocked = _unique_strings(
        _as_list(
            _get(
                applicability_data,
                "blocked",
                "blocking_constraints",
                default=[],
            )
        )
    )

    if explicit_score is not None:
        score = _clamp(
            _safe_float(
                explicit_score
            )
        )
    else:
        level_scores = {
            "high": 0.90,
            "good": 0.75,
            "medium": 0.55,
            "low": 0.30,
            "blocked": 0.05,
            "unknown": 0.40,
            "": 0.40,
        }

        score = level_scores.get(
            fit_level,
            0.40,
        )

        if required_resources:
            covered = sum(
                1
                for resource
                in required_resources
                if resource
                in available_resources
            )

            resource_fit = (
                covered
                / len(required_resources)
            )

            score = _clamp(
                0.70 * score
                + 0.30 * resource_fit
            )

        if blocked:
            score = _clamp(
                score
                * max(
                    0.0,
                    1.0
                    - 0.25
                    * len(blocked),
                )
            )

    evidence: list[str] = []
    risks: list[str] = []
    missing: list[str] = []

    if fit_level:
        evidence.append(
            f"Project fit level: {fit_level}."
        )

    if required_resources:
        evidence.append(
            "Required resources identified."
        )

    if available_resources:
        evidence.append(
            "Available resources identified."
        )

    if blocked:
        risks.extend(
            [
                f"Blocking constraint: {item}."
                for item in blocked
            ]
        )

    if constraints:
        risks.extend(
            [
                f"Known project constraint: {item}."
                for item in constraints
            ]
        )

    if not fit_level:
        missing.append(
            "Project applicability has not been explicitly assessed."
        )

    if required_resources and not available_resources:
        missing.append(
            "Available resources have not been mapped."
        )

    confidence = _clamp(
        0.45 * (
            1.0
            if fit_level
            else 0.0
        )
        + 0.25 * (
            1.0
            if required_resources
            else 0.0
        )
        + 0.20 * (
            1.0
            if available_resources
            else 0.0
        )
        + 0.10 * (
            1.0
            if not blocked
            else 0.0
        )
    )

    return OpportunityDimension(
        name="applicability",
        score=score,
        confidence=confidence,
        evidence=evidence,
        risks=risks,
        missing_data=missing,
    )


# ============================================================
# EVIDENCE QUALITY
# ============================================================

def assess_evidence_quality(
    *,
    analytics: Mapping[str, Any]
    | None = None,
    trend: Mapping[str, Any]
    | None = None,
    videos: Sequence[
        Mapping[str, Any]
    ] | None = None,
    extra_evidence: Sequence[Any]
    | None = None,
) -> OpportunityDimension:
    """
    Estimate how complete the evidence base is.

    This is deliberately separate from the opportunity score.
    A promising signal with weak evidence should remain a
    promising-but-uncertain signal.
    """

    analytics = analytics or {}
    trend = trend or {}
    videos = list(
        videos or []
    )

    metrics = _extract_metrics(
        analytics
    )

    sample_size = _safe_int(
        _get(
            metrics,
            "count",
            default=len(videos),
        )
    )

    checks = {
        "sample": sample_size >= 5,
        "views": _safe_float(
            _get(
                metrics,
                "total_views",
                "views",
                default=0,
            )
        ) > 0,
        "engagement": _safe_float(
            _get(
                metrics,
                "average_engagement_rate",
                "engagement_rate",
                default=0,
            )
        ) > 0,
        "trend": bool(
            trend.get(
                "direction"
            )
        ),
        "confidence": _safe_float(
            _get(
                trend,
                "confidence",
                default=0,
            )
        ) > 0,
    }

    score = _mean(
        [
            1.0
            if value
            else 0.0
            for value in checks.values()
        ]
    )

    extra = _unique_strings(
        extra_evidence or []
    )

    if extra:
        score = _clamp(
            score
            + min(
                0.20,
                len(extra) * 0.02,
            )
        )

    evidence = [
        f"Evidence component '{name}' is available."
        for name, available
        in checks.items()
        if available
    ]

    missing = [
        f"Evidence component '{name}' is missing."
        for name, available
        in checks.items()
        if not available
    ]

    if sample_size < 5:
        missing.append(
            "More observations are required for a stronger conclusion."
        )

    confidence = _clamp(
        score
    )

    return OpportunityDimension(
        name="evidence",
        score=score,
        confidence=confidence,
        evidence=evidence,
        risks=[],
        missing_data=missing,
    )


# ============================================================
# OVERALL SCORE
# ============================================================

def calculate_overall_score(
    dimensions: Mapping[
        str,
        OpportunityDimension,
    ],
) -> float:
    """
    Combine analytical dimensions.

    This score is an analytical summary, not a recommendation.
    """

    weights = {
        "demand": DEMAND_WEIGHT,
        "dynamics": DYNAMICS_WEIGHT,
        "competition": COMPETITION_WEIGHT,
        "applicability": APPLICABILITY_WEIGHT,
        "evidence": EVIDENCE_WEIGHT,
    }

    numerator = 0.0
    denominator = 0.0

    for name, dimension in dimensions.items():
        weight = weights.get(
            name,
            0.0,
        )

        if weight <= 0:
            continue

        numerator += (
            dimension.score
            * weight
        )

        denominator += weight

    if denominator <= EPSILON:
        return 0.0

    return _clamp(
        numerator
        / denominator
    )


def calculate_confidence(
    dimensions: Mapping[
        str,
        OpportunityDimension,
    ],
) -> float:
    if not dimensions:
        return 0.0

    weights = {
        "demand": 0.30,
        "dynamics": 0.25,
        "competition": 0.15,
        "applicability": 0.15,
        "evidence": 0.15,
    }

    numerator = 0.0
    denominator = 0.0

    for name, dimension in dimensions.items():
        weight = weights.get(
            name,
            0.0,
        )

        if weight <= 0:
            continue

        numerator += (
            dimension.confidence
            * weight
        )

        denominator += weight

    if denominator <= EPSILON:
        return 0.0

    return _clamp(
        numerator
        / denominator
    )


# ============================================================
# STRENGTHS / RISKS
# ============================================================

def collect_strengths(
    dimensions: Mapping[
        str,
        OpportunityDimension,
    ],
) -> list[str]:
    strengths: list[str] = []

    for name, dimension in dimensions.items():
        if dimension.score >= 0.70:
            strengths.append(
                f"{name}: strong positive evidence."
            )

        strengths.extend(
            dimension.evidence[
                :5
            ]
        )

    return _unique_strings(
        strengths
    )[:MAX_EVIDENCE_ITEMS]


def collect_risks(
    dimensions: Mapping[
        str,
        OpportunityDimension,
    ],
) -> list[str]:
    risks: list[str] = []

    for name, dimension in dimensions.items():
        if dimension.score <= 0.30:
            risks.append(
                f"{name}: weak analytical signal."
            )

        risks.extend(
            dimension.risks
        )

    return _unique_strings(
        risks
    )[:MAX_RISK_ITEMS]


def collect_missing_data(
    dimensions: Mapping[
        str,
        OpportunityDimension,
    ],
) -> list[str]:
    missing: list[str] = []

    for dimension in dimensions.values():
        missing.extend(
            dimension.missing_data
        )

    return _unique_strings(
        missing
    )[:MAX_MISSING_ITEMS]


# ============================================================
# SIGNALS
# ============================================================

def generate_signals(
    *,
    overall_score: float,
    confidence: float,
    dimensions: Mapping[
        str,
        OpportunityDimension,
    ],
) -> list[str]:
    signals: list[str] = []

    if overall_score >= 0.75:
        signals.append(
            "strong_opportunity_signal"
        )
    elif overall_score >= 0.55:
        signals.append(
            "positive_opportunity_signal"
        )
    elif overall_score <= 0.30:
        signals.append(
            "weak_opportunity_signal"
        )
    else:
        signals.append(
            "mixed_opportunity_signal"
        )

    if confidence >= 0.70:
        signals.append(
            "high_evidence_confidence"
        )
    elif confidence <= 0.35:
        signals.append(
            "low_evidence_confidence"
        )

    dynamics = dimensions.get(
        "dynamics"
    )

    if dynamics:
        if dynamics.score >= 0.70:
            signals.append(
                "positive_dynamics"
            )

        if dynamics.score <= 0.30:
            signals.append(
                "negative_dynamics"
            )

    competition = dimensions.get(
        "competition"
    )

    if competition:
        if competition.score <= 0.30:
            signals.append(
                "dense_competition"
            )

        if competition.score >= 0.70:
            signals.append(
                "favorable_competitive_environment"
            )

    applicability = dimensions.get(
        "applicability"
    )

    if applicability:
        if applicability.score >= 0.70:
            signals.append(
                "strong_project_fit"
            )

        if applicability.score <= 0.30:
            signals.append(
                "weak_project_fit"
            )

    return signals


# ============================================================
# MAIN ASSESSMENT
# ============================================================

def assess_opportunity(
    *,
    opportunity_id: str | None = None,
    title: str = "",
    description: str = "",
    analytics: Mapping[str, Any]
    | None = None,
    trend: Mapping[str, Any]
    | None = None,
    competition: Mapping[str, Any]
    | None = None,
    applicability: Mapping[str, Any]
    | None = None,
    constraints: Sequence[str]
    | None = None,
    demand: Mapping[str, Any]
    | None = None,
    videos: Sequence[
        Mapping[str, Any]
    ] | None = None,
    metadata: Mapping[str, Any]
    | None = None,
) -> OpportunityAssessment:
    """
    Build a complete analytical assessment.

    Director can later use this assessment as evidence
    when making a strategic decision.
    """

    analytics = analytics or {}
    trend = trend or {}
    competition = competition or {}
    applicability = applicability or {}
    demand = demand or {}

    videos = list(
        videos or []
    )

    constraints = _unique_strings(
        constraints or []
    )

    demand_dimension = assess_demand(
        analytics=analytics,
        videos=videos,
        demand_data=demand,
    )

    dynamics_dimension = assess_dynamics(
        trend=trend
    )

    competition_dimension = (
        assess_competition(
            competition_data=competition,
            videos=videos,
        )
    )

    applicability_dimension = (
        assess_applicability(
            applicability_data=applicability,
            constraints=constraints,
        )
    )

    evidence_dimension = (
        assess_evidence_quality(
            analytics=analytics,
            trend=trend,
            videos=videos,
        )
    )

    dimensions = {
        "demand": demand_dimension,
        "dynamics": dynamics_dimension,
        "competition": competition_dimension,
        "applicability": applicability_dimension,
        "evidence": evidence_dimension,
    }

    overall_score = (
        calculate_overall_score(
            dimensions
        )
    )

    confidence = (
        calculate_confidence(
            dimensions
        )
    )

    strengths = collect_strengths(
        dimensions
    )

    risks = collect_risks(
        dimensions
    )

    missing_data = (
        collect_missing_data(
            dimensions
        )
    )

    signals = generate_signals(
        overall_score=overall_score,
        confidence=confidence,
        dimensions=dimensions,
    )

    evidence = _unique_strings(
        item
        for dimension in dimensions.values()
        for item in dimension.evidence
    )[:MAX_EVIDENCE_ITEMS]

    trend_payload = dict(
        trend
    )

    competition_payload = dict(
        competition
    )

    applicability_payload = dict(
        applicability
    )

    return OpportunityAssessment(
        opportunity_id=opportunity_id,
        title=_text(title),
        description=_text(
            description
        ),
        overall_score=overall_score,
        confidence=confidence,
        dimensions=dimensions,
        strengths=strengths,
        risks=risks,
        constraints=constraints[
            :MAX_CONSTRAINT_ITEMS
        ],
        missing_data=missing_data,
        evidence=evidence,
        signals=signals,
        applicability=applicability_payload,
        competition=competition_payload,
        trend=trend_payload,
        metadata=dict(
            metadata or {}
        ),
    )


# ============================================================
# COMPARISON OF OPPORTUNITIES
# ============================================================

def compare_opportunities(
    opportunities: Sequence[
        OpportunityAssessment
        | Mapping[str, Any]
    ],
) -> list[dict[str, Any]]:
    """
    Sort opportunities by analytical score.

    This function is intentionally provided as raw analytical
    ordering only. It does not tell Director which opportunity
    to choose.

    Director remains responsible for the strategic decision.
    """

    normalized: list[
        dict[str, Any]
    ] = []

    for item in opportunities:
        if isinstance(
            item,
            OpportunityAssessment,
        ):
            data = asdict(
                item
            )
        else:
            data = dict(
                item
            )

        normalized.append(
            {
                "opportunity_id": data.get(
                    "opportunity_id"
                ),
                "title": data.get(
                    "title"
                ),
                "overall_score": _clamp(
                    _safe_float(
                        data.get(
                            "overall_score"
                        )
                    )
                ),
                "confidence": _clamp(
                    _safe_float(
                        data.get(
                            "confidence"
                        )
                    )
                ),
                "signals": list(
                    data.get(
                        "signals",
                        [],
                    )
                ),
            }
        )

    return sorted(
        normalized,
        key=lambda item: (
            item["overall_score"],
            item["confidence"],
        ),
        reverse=True,
    )


# ============================================================
# MISSING DATA / NEXT RESEARCH NEEDS
# ============================================================

def identify_research_gaps(
    assessment: OpportunityAssessment
    | Mapping[str, Any],
) -> list[str]:
    """
    Translate missing analytical evidence into research questions.

    It still does not decide what research must be executed;
    it only exposes gaps.
    """

    if isinstance(
        assessment,
        OpportunityAssessment,
    ):
        data = asdict(
            assessment
        )
    else:
        data = dict(
            assessment
        )

    gaps = _unique_strings(
        data.get(
            "missing_data",
            [],
        )
    )

    dimensions = data.get(
        "dimensions",
        {},
    )

    if isinstance(
        dimensions,
        Mapping,
    ):
        for name, raw in dimensions.items():
            if isinstance(
                raw,
                OpportunityDimension,
            ):
                raw = asdict(
                    raw
                )

            if not isinstance(
                raw,
                Mapping,
            ):
                continue

            for item in raw.get(
                "missing_data",
                [],
            ):
                gaps.append(
                    f"{name}: {item}"
                )

    return _unique_strings(
        gaps
    )[:MAX_MISSING_ITEMS]


# ============================================================
# DIRECTOR PAYLOAD
# ============================================================

def prepare_for_director(
    assessment: OpportunityAssessment
    | Mapping[str, Any],
) -> dict[str, Any]:
    """
    Produce a stable, compact structure for Director.

    Important:
        No final recommendation is generated here.
    """

    if isinstance(
        assessment,
        OpportunityAssessment,
    ):
        data = asdict(
            assessment
        )
    else:
        data = dict(
            assessment
        )

    dimensions_payload: dict[
        str,
        Any,
    ] = {}

    raw_dimensions = data.get(
        "dimensions",
        {},
    )

    if isinstance(
        raw_dimensions,
        Mapping,
    ):
        for name, dimension in raw_dimensions.items():
            if isinstance(
                dimension,
                OpportunityDimension,
            ):
                dimension = asdict(
                    dimension
                )

            if isinstance(
                dimension,
                Mapping,
            ):
                dimensions_payload[
                    name
                ] = {
                    "score": _clamp(
                        _safe_float(
                            dimension.get(
                                "score"
                            )
                        )
                    ),
                    "confidence": _clamp(
                        _safe_float(
                            dimension.get(
                                "confidence"
                            )
                        )
                    ),
                    "evidence": list(
                        dimension.get(
                            "evidence",
                            [],
                        )
                    )[
                        :MAX_EVIDENCE_ITEMS
                    ],
                    "risks": list(
                        dimension.get(
                            "risks",
                            [],
                        )
                    )[
                        :MAX_RISK_ITEMS
                    ],
                    "missing_data": list(
                        dimension.get(
                            "missing_data",
                            [],
                        )
                    )[
                        :MAX_MISSING_ITEMS
                    ],
                }

    return {
        "opportunity_id": data.get(
            "opportunity_id"
        ),
        "title": _text(
            data.get(
                "title"
            )
        ),
        "description": _text(
            data.get(
                "description"
            )
        ),
        "overall_score": _clamp(
            _safe_float(
                data.get(
                    "overall_score"
                )
            )
        ),
        "confidence": _clamp(
            _safe_float(
                data.get(
                    "confidence"
                )
            )
        ),
        "dimensions": dimensions_payload,
        "strengths": list(
            data.get(
                "strengths",
                [],
            )
        )[
            :MAX_EVIDENCE_ITEMS
        ],
        "risks": list(
            data.get(
                "risks",
                [],
            )
        )[
            :MAX_RISK_ITEMS
        ],
        "constraints": list(
            data.get(
                "constraints",
                [],
            )
        )[
            :MAX_CONSTRAINT_ITEMS
        ],
        "missing_data": list(
            data.get(
                "missing_data",
                [],
            )
        )[
            :MAX_MISSING_ITEMS
        ],
        "evidence": list(
            data.get(
                "evidence",
                [],
            )
        )[
            :MAX_EVIDENCE_ITEMS
        ],
        "signals": list(
            data.get(
                "signals",
                [],
            )
        ),
        "applicability": dict(
            data.get(
                "applicability",
                {},
            )
        ),
        "competition": dict(
            data.get(
                "competition",
                {},
            )
        ),
        "trend": dict(
            data.get(
                "trend",
                {},
            )
        ),
        "research_gaps": identify_research_gaps(
            data
        ),
        "metadata": dict(
            data.get(
                "metadata",
                {},
            )
        ),
    }


# ============================================================
# SERIALIZATION
# ============================================================

def opportunity_to_dict(
    assessment: OpportunityAssessment,
) -> dict[str, Any]:
    return asdict(
        assessment
    )


# ============================================================
# PUBLIC API
# ============================================================

__all__ = [
    "OpportunityAssessment",
    "OpportunityDimension",
    "assess_applicability",
    "assess_competition",
    "assess_demand",
    "assess_dynamics",
    "assess_evidence_quality",
    "assess_opportunity",
    "calculate_confidence",
    "calculate_overall_score",
    "collect_missing_data",
    "collect_risks",
    "collect_strengths",
    "compare_opportunities",
    "generate_signals",
    "identify_research_gaps",
    "opportunity_to_dict",
    "prepare_for_director",
]
