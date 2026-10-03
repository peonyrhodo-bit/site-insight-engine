# ai/schemas.py
"""
Structured AI response schemas for the AI Director.

These schemas define the contract between:
    AI model
and:
    Director application layer.

The schemas intentionally separate:

- analysis;
- decision;
- recommendation;
- question;
- hypothesis.

AI produces structured information.
Director remains responsible for strategic decisions.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Mapping, Sequence


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class AIResponseType(str, Enum):
    ANALYSIS = "analysis"
    DECISION = "decision"
    RECOMMENDATION = "recommendation"
    QUESTION = "question"
    HYPOTHESIS = "hypothesis"


class ConfidenceLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ActionType(str, Enum):
    RESEARCH = "research"
    ANALYZE = "analyze"
    TEST = "test"
    CREATE = "create"
    PUBLISH = "publish"
    EVALUATE = "evaluate"
    WAIT = "wait"
    ASK_USER = "ask_user"
    NONE = "none"


# ---------------------------------------------------------------------------
# Common structures
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class Evidence:
    """
    One piece of evidence supporting an AI statement.
    """

    statement: str
    source: str = ""
    source_type: str = ""
    strength: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class Risk:
    description: str
    severity: float = 0.0
    mitigation: str = ""


@dataclass(slots=True)
class MissingData:
    field: str
    reason: str = ""
    importance: float = 0.0


@dataclass(slots=True)
class AIAction:
    action_type: ActionType = ActionType.NONE
    description: str = ""
    reason: str = ""
    priority: float = 0.0
    parameters: dict[str, Any] = field(
        default_factory=dict
    )


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class AnalysisFinding:
    statement: str
    kind: str = "observation"

    confidence: float = 0.0

    evidence: list[Evidence] = field(
        default_factory=list
    )

    implications: list[str] = field(
        default_factory=list
    )


@dataclass(slots=True)
class AIAnalysis:
    response_type: AIResponseType = (
        AIResponseType.ANALYSIS
    )

    summary: str = ""

    findings: list[AnalysisFinding] = field(
        default_factory=list
    )

    evidence: list[Evidence] = field(
        default_factory=list
    )

    risks: list[Risk] = field(
        default_factory=list
    )

    missing_data: list[MissingData] = field(
        default_factory=list
    )

    confidence: float = 0.0

    confidence_level: ConfidenceLevel = (
        ConfidenceLevel.LOW
    )

    next_actions: list[AIAction] = field(
        default_factory=list
    )

    metadata: dict[str, Any] = field(
        default_factory=dict
    )


# ---------------------------------------------------------------------------
# Decision
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class AIDecision:
    response_type: AIResponseType = (
        AIResponseType.DECISION
    )

    subject: str = ""

    decision: str = ""

    rationale: str = ""

    confidence: float = 0.0

    confidence_level: ConfidenceLevel = (
        ConfidenceLevel.LOW
    )

    evidence: list[Evidence] = field(
        default_factory=list
    )

    risks: list[Risk] = field(
        default_factory=list
    )

    constraints: list[str] = field(
        default_factory=list
    )

    alternatives: list[str] = field(
        default_factory=list
    )

    next_action: AIAction = field(
        default_factory=AIAction
    )

    requires_user_confirmation: bool = True

    metadata: dict[str, Any] = field(
        default_factory=dict
    )


# ---------------------------------------------------------------------------
# Recommendation
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class RecommendationTarget:
    """
    Object the recommendation concerns.

    Examples:
    - niche;
    - topic;
    - format;
    - audience;
    - video;
    - channel;
    - experiment.
    """

    target_type: str = ""
    target_id: str | None = None
    name: str = ""
    description: str = ""


@dataclass(slots=True)
class AIRecommendation:
    response_type: AIResponseType = (
        AIResponseType.RECOMMENDATION
    )

    recommendation_id: str | None = None

    title: str = ""

    summary: str = ""

    target: RecommendationTarget = field(
        default_factory=RecommendationTarget
    )

    reason: str = ""

    audience: str = ""

    proposed_action: str = ""

    implementation: list[str] = field(
        default_factory=list
    )

    evidence: list[Evidence] = field(
        default_factory=list
    )

    risks: list[Risk] = field(
        default_factory=list
    )

    constraints: list[str] = field(
        default_factory=list
    )

    confidence: float = 0.0

    confidence_level: ConfidenceLevel = (
        ConfidenceLevel.LOW
    )

    experiment: dict[str, Any] = field(
        default_factory=dict
    )

    requires_user_confirmation: bool = True

    metadata: dict[str, Any] = field(
        default_factory=dict
    )


# ---------------------------------------------------------------------------
# Question
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class AIQuestion:
    response_type: AIResponseType = (
        AIResponseType.QUESTION
    )

    question: str = ""

    reason: str = ""

    what_it_unlocks: str = ""

    options: list[str] = field(
        default_factory=list
    )

    required: bool = True

    confidence: float = 0.0

    metadata: dict[str, Any] = field(
        default_factory=dict
    )


# ---------------------------------------------------------------------------
# Hypothesis
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class AIHypothesis:
    response_type: AIResponseType = (
        AIResponseType.HYPOTHESIS
    )

    title: str = ""

    statement: str = ""

    audience: str = ""

    topic: str = ""

    format: str = ""

    rationale: str = ""

    assumptions: list[str] = field(
        default_factory=list
    )

    test_plan: list[str] = field(
        default_factory=list
    )

    success_signals: list[str] = field(
        default_factory=list
    )

    failure_signals: list[str] = field(
        default_factory=list
    )

    evidence: list[Evidence] = field(
        default_factory=list
    )

    risks: list[Risk] = field(
        default_factory=list
    )

    confidence: float = 0.0

    confidence_level: ConfidenceLevel = (
        ConfidenceLevel.LOW
    )

    metadata: dict[str, Any] = field(
        default_factory=dict
    )


# ---------------------------------------------------------------------------
# Generic AI response
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class AIResponseEnvelope:
    """
    Generic container used when the exact response type is not known yet.
    """

    response_type: AIResponseType

    summary: str = ""

    payload: dict[str, Any] = field(
        default_factory=dict
    )

    confidence: float = 0.0

    metadata: dict[str, Any] = field(
        default_factory=dict
    )


# ---------------------------------------------------------------------------
# Conversion helpers
# ---------------------------------------------------------------------------


def _safe_float(
    value: Any,
    default: float = 0.0,
) -> float:
    try:
        number = float(value)

        if number != number:
            return default

        return max(0.0, min(1.0, number))
    except (TypeError, ValueError):
        return default


def _safe_text(
    value: Any,
    default: str = "",
) -> str:
    if value is None:
        return default

    return str(value).strip()


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []

    if isinstance(value, list):
        return value

    if isinstance(value, tuple):
        return list(value)

    return [value]


def _confidence_level(
    confidence: float,
) -> ConfidenceLevel:
    if confidence >= 0.75:
        return ConfidenceLevel.HIGH

    if confidence >= 0.45:
        return ConfidenceLevel.MEDIUM

    return ConfidenceLevel.LOW


def _action_type(
    value: Any,
) -> ActionType:
    raw = _safe_text(value).lower()

    for action_type in ActionType:
        if action_type.value == raw:
            return action_type

    return ActionType.NONE


# ---------------------------------------------------------------------------
# Parsing evidence
# ---------------------------------------------------------------------------


def evidence_from_dict(
    data: Mapping[str, Any],
) -> Evidence:
    return Evidence(
        statement=_safe_text(
            data.get("statement")
        ),
        source=_safe_text(
            data.get("source")
        ),
        source_type=_safe_text(
            data.get("source_type")
        ),
        strength=_safe_float(
            data.get("strength")
        ),
        metadata=dict(
            data.get("metadata")
            or {}
        ),
    )


def risk_from_dict(
    data: Mapping[str, Any],
) -> Risk:
    return Risk(
        description=_safe_text(
            data.get("description")
        ),
        severity=_safe_float(
            data.get("severity")
        ),
        mitigation=_safe_text(
            data.get("mitigation")
        ),
    )


def missing_data_from_dict(
    data: Mapping[str, Any],
) -> MissingData:
    return MissingData(
        field=_safe_text(
            data.get("field")
        ),
        reason=_safe_text(
            data.get("reason")
        ),
        importance=_safe_float(
            data.get("importance")
        ),
    )


def action_from_dict(
    data: Mapping[str, Any],
) -> AIAction:
    return AIAction(
        action_type=_action_type(
            data.get("action_type")
        ),
        description=_safe_text(
            data.get("description")
        ),
        reason=_safe_text(
            data.get("reason")
        ),
        priority=_safe_float(
            data.get("priority")
        ),
        parameters=dict(
            data.get("parameters")
            or {}
        ),
    )


# ---------------------------------------------------------------------------
# Parsing complete responses
# ---------------------------------------------------------------------------


def analysis_from_dict(
    data: Mapping[str, Any],
) -> AIAnalysis:
    confidence = _safe_float(
        data.get("confidence")
    )

    findings: list[AnalysisFinding] = []

    for raw in _as_list(
        data.get("findings")
    ):
        if not isinstance(raw, Mapping):
            continue

        findings.append(
            AnalysisFinding(
                statement=_safe_text(
                    raw.get("statement")
                ),
                kind=_safe_text(
                    raw.get("kind"),
                    "observation",
                ),
                confidence=_safe_float(
                    raw.get("confidence")
                ),
                evidence=[
                    evidence_from_dict(item)
                    for item in _as_list(
                        raw.get("evidence")
                    )
                    if isinstance(item, Mapping)
                ],
                implications=[
                    _safe_text(item)
                    for item in _as_list(
                        raw.get("implications")
                    )
                    if _safe_text(item)
                ],
            )
        )

    return AIAnalysis(
        summary=_safe_text(
            data.get("summary")
        ),
        findings=findings,
        evidence=[
            evidence_from_dict(item)
            for item in _as_list(
                data.get("evidence")
            )
            if isinstance(item, Mapping)
        ],
        risks=[
            risk_from_dict(item)
            for item in _as_list(
                data.get("risks")
            )
            if isinstance(item, Mapping)
        ],
        missing_data=[
            missing_data_from_dict(item)
            for item in _as_list(
                data.get("missing_data")
            )
            if isinstance(item, Mapping)
        ],
        confidence=confidence,
        confidence_level=_confidence_level(
            confidence
        ),
        next_actions=[
            action_from_dict(item)
            for item in _as_list(
                data.get("next_actions")
            )
            if isinstance(item, Mapping)
        ],
        metadata=dict(
            data.get("metadata")
            or {}
        ),
    )


def decision_from_dict(
    data: Mapping[str, Any],
) -> AIDecision:
    confidence = _safe_float(
        data.get("confidence")
    )

    raw_action = data.get("next_action")

    if not isinstance(raw_action, Mapping):
        raw_action = {}

    return AIDecision(
        subject=_safe_text(
            data.get("subject")
        ),
        decision=_safe_text(
            data.get("decision")
        ),
        rationale=_safe_text(
            data.get("rationale")
        ),
        confidence=confidence,
        confidence_level=_confidence_level(
            confidence
        ),
        evidence=[
            evidence_from_dict(item)
            for item in _as_list(
                data.get("evidence")
            )
            if isinstance(item, Mapping)
        ],
        risks=[
            risk_from_dict(item)
            for item in _as_list(
                data.get("risks")
            )
            if isinstance(item, Mapping)
        ],
        constraints=[
            _safe_text(item)
            for item in _as_list(
                data.get("constraints")
            )
            if _safe_text(item)
        ],
        alternatives=[
            _safe_text(item)
            for item in _as_list(
                data.get("alternatives")
            )
            if _safe_text(item)
        ],
        next_action=action_from_dict(
            raw_action
        ),
        requires_user_confirmation=bool(
            data.get(
                "requires_user_confirmation",
                True,
            )
        ),
        metadata=dict(
            data.get("metadata")
            or {}
        ),
    )


def recommendation_from_dict(
    data: Mapping[str, Any],
) -> AIRecommendation:
    confidence = _safe_float(
        data.get("confidence")
    )

    raw_target = data.get("target")

    if not isinstance(raw_target, Mapping):
        raw_target = {}

    return AIRecommendation(
        recommendation_id=(
            _safe_text(
                data.get("recommendation_id")
            )
            or None
        ),
        title=_safe_text(
            data.get("title")
        ),
        summary=_safe_text(
            data.get("summary")
        ),
        target=RecommendationTarget(
            target_type=_safe_text(
                raw_target.get("target_type")
            ),
            target_id=(
                _safe_text(
                    raw_target.get("target_id")
                )
                or None
            ),
            name=_safe_text(
                raw_target.get("name")
            ),
            description=_safe_text(
                raw_target.get("description")
            ),
        ),
        reason=_safe_text(
            data.get("reason")
        ),
        audience=_safe_text(
            data.get("audience")
        ),
        proposed_action=_safe_text(
            data.get("proposed_action")
        ),
        implementation=[
            _safe_text(item)
            for item in _as_list(
                data.get("implementation")
            )
            if _safe_text(item)
        ],
        evidence=[
            evidence_from_dict(item)
            for item in _as_list(
                data.get("evidence")
            )
            if isinstance(item, Mapping)
        ],
        risks=[
            risk_from_dict(item)
            for item in _as_list(
                data.get("risks")
            )
            if isinstance(item, Mapping)
        ],
        constraints=[
            _safe_text(item)
            for item in _as_list(
                data.get("constraints")
            )
            if _safe_text(item)
        ],
        confidence=confidence,
        confidence_level=_confidence_level(
            confidence
        ),
        experiment=dict(
            data.get("experiment")
            or {}
        ),
        requires_user_confirmation=bool(
            data.get(
                "requires_user_confirmation",
                True,
            )
        ),
        metadata=dict(
            data.get("metadata")
            or {}
        ),
    )


def question_from_dict(
    data: Mapping[str, Any],
) -> AIQuestion:
    confidence = _safe_float(
        data.get("confidence")
    )

    return AIQuestion(
        question=_safe_text(
            data.get("question")
        ),
        reason=_safe_text(
            data.get("reason")
        ),
        what_it_unlocks=_safe_text(
            data.get("what_it_unlocks")
        ),
        options=[
            _safe_text(item)
            for item in _as_list(
                data.get("options")
            )
            if _safe_text(item)
        ],
        required=bool(
            data.get(
                "required",
                True,
            )
        ),
        confidence=confidence,
        metadata=dict(
            data.get("metadata")
            or {}
        ),
    )


def hypothesis_from_dict(
    data: Mapping[str, Any],
) -> AIHypothesis:
    confidence = _safe_float(
        data.get("confidence")
    )

    return AIHypothesis(
        title=_safe_text(
            data.get("title")
        ),
        statement=_safe_text(
            data.get("statement")
        ),
        audience=_safe_text(
            data.get("audience")
        ),
        topic=_safe_text(
            data.get("topic")
        ),
        format=_safe_text(
            data.get("format")
        ),
        rationale=_safe_text(
            data.get("rationale")
        ),
        assumptions=[
            _safe_text(item)
            for item in _as_list(
                data.get("assumptions")
            )
            if _safe_text(item)
        ],
        test_plan=[
            _safe_text(item)
            for item in _as_list(
                data.get("test_plan")
            )
            if _safe_text(item)
        ],
        success_signals=[
            _safe_text(item)
            for item in _as_list(
                data.get("success_signals")
            )
            if _safe_text(item)
        ],
        failure_signals=[
            _safe_text(item)
            for item in _as_list(
                data.get("failure_signals")
            )
            if _safe_text(item)
        ],
        evidence=[
            evidence_from_dict(item)
            for item in _as_list(
                data.get("evidence")
            )
            if isinstance(item, Mapping)
        ],
        risks=[
            risk_from_dict(item)
            for item in _as_list(
                data.get("risks")
            )
            if isinstance(item, Mapping)
        ],
        confidence=confidence,
        confidence_level=_confidence_level(
            confidence
        ),
        metadata=dict(
            data.get("metadata")
            or {}
        ),
    )


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------


def to_dict(
    value: Any,
) -> dict[str, Any]:
    """
    Convert one of the AI schema dataclasses into a dictionary.
    """

    if hasattr(value, "__dataclass_fields__"):
        return asdict(value)

    if isinstance(value, Mapping):
        return dict(value)

    raise TypeError(
        f"Unsupported AI schema type: {type(value)!r}"
    )


def schema_to_json_schema(
    schema_name: str,
) -> dict[str, Any]:
    """
    Return a lightweight JSON-schema-like description.

    This is intentionally provider-neutral and can later be extended
    for strict structured-output providers.
    """

    schemas: dict[str, dict[str, Any]] = {
        "analysis": {
            "type": "object",
            "required": [
                "summary",
                "findings",
                "confidence",
            ],
            "properties": {
                "summary": {"type": "string"},
                "findings": {"type": "array"},
                "evidence": {"type": "array"},
                "risks": {"type": "array"},
                "missing_data": {"type": "array"},
                "confidence": {
                    "type": "number",
                    "minimum": 0,
                    "maximum": 1,
                },
                "next_actions": {"type": "array"},
            },
        },
        "decision": {
            "type": "object",
            "required": [
                "subject",
                "decision",
                "rationale",
                "confidence",
            ],
            "properties": {
                "subject": {"type": "string"},
                "decision": {"type": "string"},
                "rationale": {"type": "string"},
                "confidence": {
                    "type": "number",
                    "minimum": 0,
                    "maximum": 1,
                },
                "evidence": {"type": "array"},
                "risks": {"type": "array"},
                "constraints": {"type": "array"},
                "alternatives": {"type": "array"},
                "next_action": {"type": "object"},
            },
        },
        "recommendation": {
            "type": "object",
            "required": [
                "title",
                "summary",
                "reason",
                "proposed_action",
                "confidence",
            ],
            "properties": {
                "title": {"type": "string"},
                "summary": {"type": "string"},
                "reason": {"type": "string"},
                "audience": {"type": "string"},
                "proposed_action": {"type": "string"},
                "implementation": {"type": "array"},
                "evidence": {"type": "array"},
                "risks": {"type": "array"},
                "experiment": {"type": "object"},
                "confidence": {
                    "type": "number",
                    "minimum": 0,
                    "maximum": 1,
                },
            },
        },
        "question": {
            "type": "object",
            "required": [
                "question",
                "reason",
            ],
            "properties": {
                "question": {"type": "string"},
                "reason": {"type": "string"},
                "what_it_unlocks": {
                    "type": "string"
                },
                "options": {"type": "array"},
                "required": {"type": "boolean"},
            },
        },
        "hypothesis": {
            "type": "object",
            "required": [
                "title",
                "statement",
                "audience",
                "topic",
                "format",
                "test_plan",
            ],
            "properties": {
                "title": {"type": "string"},
                "statement": {"type": "string"},
                "audience": {"type": "string"},
                "topic": {"type": "string"},
                "format": {"type": "string"},
                "rationale": {"type": "string"},
                "assumptions": {"type": "array"},
                "test_plan": {"type": "array"},
                "success_signals": {"type": "array"},
                "failure_signals": {"type": "array"},
                "evidence": {"type": "array"},
                "risks": {"type": "array"},
                "confidence": {
                    "type": "number",
                    "minimum": 0,
                    "maximum": 1,
                },
            },
        },
    }

    key = (schema_name or "").strip().lower()

    if key not in schemas:
        raise KeyError(
            f"Unknown AI schema: {schema_name}"
        )

    return schemas[key]


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def validate_response(
    response_type: AIResponseType | str,
    data: Mapping[str, Any],
) -> tuple[bool, list[str]]:
    """
    Lightweight validation before AI output reaches Director.
    """

    if isinstance(response_type, AIResponseType):
        response_type = response_type.value

    response_type = str(
        response_type
    ).strip().lower()

    errors: list[str] = []

    required_fields: dict[str, list[str]] = {
        "analysis": [
            "summary",
            "findings",
        ],
        "decision": [
            "subject",
            "decision",
            "rationale",
        ],
        "recommendation": [
            "title",
            "summary",
            "reason",
            "proposed_action",
        ],
        "question": [
            "question",
            "reason",
        ],
        "hypothesis": [
            "title",
            "statement",
            "audience",
            "topic",
            "format",
            "test_plan",
        ],
    }

    if response_type not in required_fields:
        errors.append(
            f"Unknown response type: {response_type}"
        )
        return False, errors

    for field_name in required_fields[response_type]:
        value = data.get(field_name)

        if value is None:
            errors.append(
                f"Missing required field: {field_name}"
            )
            continue

        if isinstance(value, str) and not value.strip():
            errors.append(
                f"Required field is empty: {field_name}"
            )

    confidence = data.get("confidence")

    if confidence is not None:
        try:
            numeric = float(confidence)

            if numeric < 0 or numeric > 1:
                errors.append(
                    "confidence must be between 0 and 1"
                )

        except (TypeError, ValueError):
            errors.append(
                "confidence must be numeric"
            )

    return not errors, errors


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


__all__ = [
    "AIResponseType",
    "ConfidenceLevel",
    "ActionType",
    "Evidence",
    "Risk",
    "MissingData",
    "AIAction",
    "AnalysisFinding",
    "AIAnalysis",
    "AIDecision",
    "RecommendationTarget",
    "AIRecommendation",
    "AIQuestion",
    "AIHypothesis",
    "AIResponseEnvelope",
    "evidence_from_dict",
    "risk_from_dict",
    "missing_data_from_dict",
    "action_from_dict",
    "analysis_from_dict",
    "decision_from_dict",
    "recommendation_from_dict",
    "question_from_dict",
    "hypothesis_from_dict",
    "to_dict",
    "schema_to_json_schema",
    "validate_response",
]
