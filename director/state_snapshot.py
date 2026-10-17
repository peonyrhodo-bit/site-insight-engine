"""Build a complete, evidence-backed pre-cycle snapshot for Director.

The snapshot is intentionally explicit: every required parameter is represented
as known, unknown, or not_applicable. Unknown is a valid honest state; omission
is not. This module is pure and does not make network calls.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping


SNAPSHOT_SCHEMA_VERSION = 1
STATUS_KNOWN = "known"
STATUS_UNKNOWN = "unknown"
STATUS_NOT_APPLICABLE = "not_applicable"

REQUIRED_PARAMETERS: tuple[tuple[int, str, str], ...] = (
    (1, "ai_availability", "Доступность ИИ"),
    (2, "youtube_api_and_sources", "YouTube API и другие источники"),
    (3, "persistence_and_memory", "Сохранение данных и память"),
    (4, "website_and_recommendation_persistence", "Сайт и сохранение рекомендаций"),
    (5, "scheduler_health", "Работоспособность планировщика"),
    (6, "last_successful_cycle", "Последний успешный цикл"),
    (7, "errors_and_unfinished_operations", "Ошибки и незавершённые операции"),
    (8, "concurrent_cycle", "Другой выполняющийся цикл"),
    (9, "research_completion", "Завершённые и незавершённые исследования"),
    (10, "result_reuse", "Повторное использование результатов"),
    (11, "under_researched_directions", "Недостаточно изученные направления"),
    (12, "hypotheses", "Гипотезы для проверки"),
    (13, "forecasts", "Прогнозы для сравнения с фактами"),
    (14, "due_measurements", "Наступившие повторные измерения"),
    (15, "new_data_since_last_cycle", "Новые данные с прошлого цикла"),
    (16, "created_recommendations", "Созданные рекомендации"),
    (17, "recommendations_awaiting_user", "Ожидают решения пользователя"),
    (18, "recommendations_under_discussion", "Обсуждаются"),
    (19, "accepted_rejected_decisions", "Принятые или отклонённые решения"),
    (20, "video_preparation_tasks", "Задачи подготовки видео и их статусы"),
    (21, "changed_conclusions", "Новые данные меняют прежние выводы"),
    (22, "unified_quota", "Квота единого менеджера"),
    (23, "free_tools", "Доступные бесплатные инструменты"),
    (24, "source_restrictions", "Ограничения источников и ошибки доступа"),
    (25, "production_budget_mode", "Режим бюджета производства"),
    (26, "pending_user_tasks", "Ожидающие пользовательские задачи"),
    (27, "end_of_day_plan", "Выполнение плана до конца суток"),
)


# Freshness limits are part of the snapshot contract. They measure age of the
# primary evidence, not how recently the snapshot itself was generated.
FRESHNESS_MAX_AGE_SECONDS: dict[str, int] = {
    "ai_availability": 300,
    "youtube_api_and_sources": 300,
    "persistence_and_memory": 300,
    "website_and_recommendation_persistence": 300,
    "scheduler_health": 300,
    "last_successful_cycle": 86400,
    "errors_and_unfinished_operations": 3600,
    "concurrent_cycle": 300,
    "research_completion": 86400,
    "result_reuse": 86400,
    "under_researched_directions": 86400,
    "hypotheses": 86400,
    "forecasts": 86400,
    "due_measurements": 3600,
    "new_data_since_last_cycle": 86400,
    "created_recommendations": 86400,
    "recommendations_awaiting_user": 3600,
    "recommendations_under_discussion": 3600,
    "accepted_rejected_decisions": 86400,
    "video_preparation_tasks": 3600,
    "changed_conclusions": 86400,
    "unified_quota": 300,
    "free_tools": 604800,
    "source_restrictions": 3600,
    "production_budget_mode": 86400,
    "pending_user_tasks": 3600,
    "end_of_day_plan": 86400,
}

_TIMESTAMP_KEYS = (
    "checked_at", "captured_at", "updated_at", "completed_at",
    "created_at", "last_seen", "observed_at", "timestamp", "run_at",
)


def _parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _latest_evidence_timestamp(value: Any) -> datetime | None:
    """Find the newest explicit evidence timestamp without treating absence as fresh."""
    candidates: list[datetime] = []
    if isinstance(value, dict):
        for key in _TIMESTAMP_KEYS:
            parsed = _parse_timestamp(value.get(key))
            if parsed is not None:
                candidates.append(parsed)
        for key in ("data_json", "data", "metadata", "value", "result"):
            nested = value.get(key)
            if isinstance(nested, (dict, list)):
                parsed = _latest_evidence_timestamp(nested)
                if parsed is not None:
                    candidates.append(parsed)
    elif isinstance(value, list):
        for item in value:
            parsed = _latest_evidence_timestamp(item)
            if parsed is not None:
                candidates.append(parsed)
    return max(candidates) if candidates else None


def assess_freshness(
    value: Any,
    *,
    max_age_seconds: int,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Assess evidence freshness; missing/invalid timestamps remain unknown."""
    checked_at = now or datetime.now(timezone.utc)
    if checked_at.tzinfo is None:
        checked_at = checked_at.replace(tzinfo=timezone.utc)
    checked_at = checked_at.astimezone(timezone.utc)
    observed_at = _latest_evidence_timestamp(value)
    result: dict[str, Any] = {
        "snapshot_checked_at": checked_at.isoformat(),
        "source_observed_at": observed_at.isoformat() if observed_at else None,
        "max_age_seconds": max(0, int(max_age_seconds)),
        "age_seconds": None,
        "status": "unknown",
        "on_unavailable": "mark unknown; do not substitute a healthy/default value",
    }
    if observed_at is not None:
        age = max(0.0, (checked_at - observed_at).total_seconds())
        result["age_seconds"] = int(age)
        result["status"] = "fresh" if age <= max_age_seconds else "stale"
    return result


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _entry(value: Any = None, *, known: bool = False, evidence: str = "",
           reason: str = "") -> dict[str, Any]:
    if known:
        return {"status": STATUS_KNOWN, "value": value, "evidence": evidence}
    return {
        "status": STATUS_UNKNOWN,
        "value": None,
        "evidence": evidence,
        "reason": reason or "Источник значения не подключён к снимку Director.",
    }



def _record_payload(item: Any) -> dict[str, Any]:
    """Flatten a persisted result/action row without discarding its provenance."""
    row = _dict(item)
    nested = _dict(row.get("data_json")) or _dict(row.get("data")) or _dict(row.get("source_data"))
    return {**nested, **row}


def _record_kind(item: Any) -> str:
    row = _record_payload(item)
    return str(row.get("result_type") or row.get("type") or row.get("kind")
               or row.get("action_type") or row.get("event_type") or "").strip().lower().replace("-", "_").replace(" ", "_")


def _typed_records(records: list[Any], *kinds: str) -> list[dict[str, Any]]:
    accepted = {kind.lower().replace("-", "_").replace(" ", "_") for kind in kinds}
    result: list[dict[str, Any]] = []
    for item in records:
        payload = _record_payload(item)
        kind = _record_kind(item)
        if kind in accepted or any(kind.endswith("_" + candidate) for candidate in accepted):
            result.append(payload)
    return result


def _first_present(*values: Any) -> Any:
    for value in values:
        if value is not None and value != "" and value != [] and value != {}:
            return value
    return None

def _status_of(item: Any) -> str:
    row = _dict(item)
    nested = _dict(row.get("data_json")) or _dict(row.get("data"))
    return str(row.get("status") or nested.get("status") or "").strip().lower()


def _latest_successful_run(runs: list[Any]) -> dict[str, Any] | None:
    successful = [
        _dict(item) for item in runs
        if _status_of(item) in {"completed", "complete", "success", "succeeded"}
    ]
    if not successful:
        return None
    return max(
        successful,
        key=lambda item: str(
            item.get("updated_at") or item.get("completed_at")
            or item.get("created_at")
            or _dict(item.get("data_json")).get("updated_at")
            or _dict(item.get("data_json")).get("completed_at")
            or _dict(item.get("data_json")).get("created_at") or ""
        ),
    )


def build_unified_state_snapshot(context: Any, *, runtime_health: Mapping[str, Any] | None = None,
                                 last_cycle: Any = None) -> dict[str, Any]:
    """Return a 27-parameter snapshot with explicit status and provenance.

    `runtime_health` is supplied by the orchestrator after actual probes.
    Merely configuring a service is not treated as proof that it is reachable.
    """
    now = datetime.now(timezone.utc).isoformat()
    metadata = _dict(getattr(context, "metadata", {}))
    health = dict(runtime_health or _dict(metadata.get("runtime_health")))
    project_state = _dict(metadata.get("project_state"))
    inventory = _dict(metadata.get("data_inventory"))
    if not inventory:
        inventory = _dict(project_state.get("inventory"))
    memory_state = _dict(metadata.get("memory_state"))
    runs = _list(memory_state.get("recent_runs")) or _list(metadata.get("recent_runs"))
    decisions = _list(getattr(context, "decisions", []))
    recommendations = _list(getattr(context, "recommendations", []))
    actions = _list(memory_state.get("unfinished_actions"))
    # Memory 2.0 also returns the bounded raw action history at the top level.
    # Include it so statuses such as waiting_for_user are not lost merely
    # because they are excluded from the semantic unfinished-actions subset.
    for action in _list(memory_state.get("recent_actions")) + _list(metadata.get("actions")) + _list(metadata.get("recent_actions")):
        if action not in actions:
            actions.append(action)
    events = _list(memory_state.get("recent_events")) or _list(metadata.get("recent_events"))
    results = _list(memory_state.get("recent_results")) or _list(metadata.get("recent_results"))
    pending_memory_recommendations = _list(memory_state.get("pending_recommendations"))
    unresolved_memory_decisions = _list(memory_state.get("unresolved_decisions"))
    research = _list(getattr(context, "research_history", []))
    if not research:
        research = _list(metadata.get("research_sets")) or results
    observations = _list(getattr(context, "observations", []))
    constraints = _list(getattr(context, "constraints", []))
    feedback = _list(getattr(context, "feedback", []))
    capabilities = _dict(metadata.get("capabilities"))
    connected = _dict(capabilities.get("connected_services"))
    quota = _dict(project_state.get("quota"))
    freshness = _dict(project_state.get("freshness"))

    entries: dict[str, dict[str, Any]] = {}

    def put(key: str, value: Any = None, *, known: bool = False,
            evidence: str = "", reason: str = "") -> None:
        entries[key] = _entry(value, known=known, evidence=evidence, reason=reason)

    # Operational health: explicit probes take precedence over configuration.
    for key, service_name, configured in (
        ("ai_availability", "ai", getattr(context, "ai_service", None) is not None),
        ("youtube_api_and_sources", "youtube_sources", False),
        ("website_and_recommendation_persistence", "website", False),
        ("scheduler_health", "scheduler", False),
    ):
        probe = _dict(health.get(service_name))
        if probe.get("status") in {"healthy", "available", "unavailable", "degraded"}:
            put(key, probe, known=True, evidence=f"runtime_health.{service_name}")
        else:
            put(key, None, reason=(
                "Сервис сконфигурирован, но фактическая проверка доступности не передана."
                if configured else
                f"Нет результата фактической проверки runtime_health.{service_name}."
            ))

    memory_probe = _dict(health.get("memory"))
    if memory_probe.get("status") in {"healthy", "available", "unavailable", "degraded"}:
        put("persistence_and_memory", memory_probe, known=True, evidence="runtime_health.memory")
    else:
        put("persistence_and_memory", None, reason="Не зафиксирован результат проверки чтения памяти/хранилища.")

    active_statuses = {"requested", "registered", "running", "initializing", "in_progress"}
    persisted_active_runs = [item for item in runs if _status_of(item) in active_statuses]
    active = _dict(health.get("active_cycle"))
    if persisted_active_runs:
        put("concurrent_cycle", {
            "active": True,
            "runs": persisted_active_runs,
            "source": "memory_state.recent_runs",
            "scope": "recent bounded run history",
        }, known=True, evidence="memory_state.recent_runs")
    elif active.get("status") in {"healthy", "available", "unavailable", "degraded"}:
        put("concurrent_cycle", {
            **active,
            "active": bool(active.get("active", False)),
            "persisted_recent_active_runs": 0 if runs else None,
        }, known=True, evidence="runtime_health.active_cycle")
    elif runs:
        put("concurrent_cycle", {
            "active": False,
            "source": "memory_state.recent_runs",
            "scope": "recent bounded run history",
        }, known=True, evidence="memory_state.recent_runs")
    else:
        put("concurrent_cycle", None, reason="Нет подтверждённого снимка блокировки и истории активных запусков.")

    last_success = _latest_successful_run(runs)
    if last_success:
        put("last_successful_cycle", last_success, known=True, evidence="memory_state.recent_runs")
    else:
        put("last_successful_cycle", None, reason="В доступной истории не найден успешный запуск; это не доказывает, что его никогда не было.")

    unfinished_runs = [
        item for item in runs
        if _status_of(item) in {"requested", "registered", "running", "initializing", "partial", "failed", "pending"}
    ]
    error_events = [
        item for item in events
        if any(token in str(_dict(item).get("event_type") or _dict(item).get("type") or "").lower()
               for token in ("error", "fail", "timeout", "blocked"))
    ]
    put("errors_and_unfinished_operations",
        {"unfinished_runs": unfinished_runs, "unfinished_actions": actions, "error_events": error_events},
        known=bool(runs or actions or events),
        evidence="memory_state.recent_runs/recent_actions/recent_events",
        reason="Нет доступных журналов запусков, действий и событий.")

    # Research and strategy state. A zero count is only known when its source is
    # actually present; missing collections remain unknown.
    put("research_completion", research, known=bool(research), evidence="DirectorContext.research_history",
        reason="История исследований не загружена в контекст.")
    result_reuse = _dict(health.get("result_reuse"))
    if result_reuse.get("status") in {"healthy", "available", "unavailable", "degraded"}:
        put("result_reuse", result_reuse, known=True, evidence="runtime_health.result_reuse")
    else:
        reuse_rows = []
        for item in research:
            row = _record_payload(item)
            if any(key in row for key in ("reused_video_ids", "reusable_video_ids", "reuse_count", "reused_count")):
                reuse_rows.append({
                    "research_id": row.get("research_id") or row.get("id"),
                    "reused_video_ids": row.get("reused_video_ids", []),
                    "reusable_video_ids": row.get("reusable_video_ids", []),
                    "reuse_count": row.get("reuse_count", row.get("reused_count")),
                })
        put("result_reuse", {"records": reuse_rows, "measured": True} if reuse_rows else None,
            known=bool(reuse_rows), evidence="persisted research-set reuse fields",
            reason="Не измерено, переиспользуются ли сохранённые результаты вместо повторных запросов.")

    under_researched = metadata.get("under_researched_directions")
    gap_records = []
    if under_researched is None:
        for item in research:
            row = _record_payload(item)
            gaps = row.get("gaps") or row.get("missing_data") or row.get("data_gaps")
            if gaps:
                gap_records.append({"research_id": row.get("research_id") or row.get("id"), "gaps": gaps})
        if gap_records:
            under_researched = {"research_gaps": gap_records, "derived_from": "persisted research records; gaps are proxies, not a full topic coverage score"}
    put("under_researched_directions", under_researched,
        known=under_researched is not None, evidence="metadata.under_researched_directions or persisted research gaps",
        reason="Инвентарь тем и число запросов не показывают, какие именно направления недостаточно изучены; в сохранённых исследованиях нет явных gaps.")

    hypothesis = metadata.get("current_hypothesis")
    hypotheses = metadata.get("hypotheses")
    if hypotheses is None and hypothesis is None:
        persisted_hypotheses = _typed_records(results, "hypothesis", "director_hypothesis", "hypothesis_result")
        if not persisted_hypotheses:
            persisted_hypotheses = [
                _record_payload(item) for item in decisions
                if _first_present(_dict(_record_payload(item).get("data_json")).get("hypothesis"), _record_payload(item).get("hypothesis")) is not None
            ]
        if persisted_hypotheses:
            hypotheses = persisted_hypotheses
    put("hypotheses", hypotheses if hypotheses is not None else hypothesis,
        known=hypotheses is not None or isinstance(hypothesis, dict),
        evidence="metadata.hypotheses/current_hypothesis or typed persisted Director results",
        reason="Нет устойчивого реестра гипотез со статусами проверки и в истории результатов не найдены записи типа hypothesis.")

    forecasts = metadata.get("forecasts")
    if forecasts is None:
        forecasts = _typed_records(results, "forecast", "director_forecast", "forecast_result") or None
    put("forecasts", forecasts, known=forecasts is not None, evidence="metadata.forecasts or typed persisted Director results",
        reason="Нет реестра прогнозов и результатов их сравнения с фактами.")
    due = metadata.get("due_measurements")
    if due is None:
        due = _typed_records(results, "due_measurement", "repeat_measurement", "measurement_schedule") or None
    due_evidence = "metadata.due_measurements or typed persisted measurement records"
    if due is None:
        scheduler_state = _dict(health.get("scheduler"))
        scheduled_items = _list(scheduler_state.get("scheduled_items"))
        measurement_schedules = []
        for item in scheduled_items:
            row = _record_payload(item)
            schedule_metadata = _dict(row.get("metadata"))
            descriptor = " ".join(str(value or "") for value in (
                row.get("reason"), row.get("schedule_type"), schedule_metadata.get("kind"),
                schedule_metadata.get("task_type"), schedule_metadata.get("purpose"),
                schedule_metadata.get("category"),
            )).lower()
            if any(token in descriptor for token in ("measurement", "repeat_measurement", "замер", "измерен")):
                run_at = row.get("run_at")
                try:
                    parsed_due = datetime.fromisoformat(str(run_at).replace("Z", "+00:00"))
                    if parsed_due.tzinfo is None:
                        parsed_due = parsed_due.replace(tzinfo=timezone.utc)
                    is_due = parsed_due <= datetime.now(timezone.utc)
                except (TypeError, ValueError):
                    is_due = None
                measurement_schedules.append({
                    **row,
                    "due": is_due,
                    "due_check": "run_at compared with current UTC time" if is_due is not None else "run_at missing or invalid",
                })
        if measurement_schedules:
            due = {
                "due": [item for item in measurement_schedules if item.get("due") is True],
                "scheduled_measurements": measurement_schedules,
                "source": "runtime_health.scheduler.scheduled_items",
                "scheduler_durability": "in_memory_only",
            }
            due_evidence = "explicit measurement-tagged schedules in the inspected in-memory scheduler queue"
    put("due_measurements", due, known=due is not None, evidence=due_evidence,
        reason="Нет вычисленного списка наступивших повторных измерений или сохранённого расписания измерений с явной меткой.")
    changes = metadata.get("new_data_since_last_cycle")
    if changes is not None:
        put("new_data_since_last_cycle", changes, known=True, evidence="metadata.new_data_since_last_cycle")
    else:
        last_success = _latest_successful_run(runs)
        last_success_at = None
        if last_success:
            nested_run = _dict(last_success.get("data_json")) or _dict(last_success.get("data"))
            last_success_at = (
                last_success.get("completed_at") or last_success.get("updated_at")
                or nested_run.get("completed_at") or nested_run.get("updated_at")
                or last_success.get("created_at") or nested_run.get("created_at")
            )
        latest_observation_at = None
        for observation in observations:
            if not isinstance(observation, dict):
                continue
            captured = (
                observation.get("snapshot_captured_at")
                or observation.get("captured_at")
                or observation.get("updated_at")
            )
            if captured and (latest_observation_at is None or str(captured) > str(latest_observation_at)):
                latest_observation_at = captured
        if last_success_at and latest_observation_at:
            put("new_data_since_last_cycle", {
                "latest_observation_at": latest_observation_at,
                "last_successful_cycle_at": last_success_at,
                "newer_observation_exists": str(latest_observation_at) > str(last_success_at),
                "comparison": "latest available observation timestamp vs last successful cycle timestamp",
            }, known=True, evidence="observations timestamps + memory_state.recent_runs",
                reason="This is a timestamp-based signal, not a full row-by-row change diff.")
        else:
            put("new_data_since_last_cycle", None,
                evidence="project_state.freshness" if freshness else "",
                reason="Нет сопоставимых временных меток последнего успешного цикла и последнего наблюдения.")

    if not recommendations:
        recommendations = pending_memory_recommendations
    put("created_recommendations", recommendations, known=bool(recommendations),
        evidence="DirectorContext.recommendations or memory_state.pending_recommendations", reason="Рекомендации не загружены в контекст.")
    awaiting = [r for r in recommendations if _status_of(r) in {"new", "draft", "pending", "proposed", "deferred"}]
    discussed = [r for r in recommendations if _status_of(r) in {"discussed", "under_discussion"}]
    put("recommendations_awaiting_user", awaiting, known=bool(recommendations),
        evidence="persisted recommendation status values", reason="Нельзя определить очередь решений без загруженных рекомендаций.")
    put("recommendations_under_discussion", discussed, known=bool(recommendations),
        evidence="persisted recommendation status values", reason="Нельзя определить обсуждаемые рекомендации без загруженных рекомендаций.")
    if not decisions:
        decisions = unresolved_memory_decisions
    put("accepted_rejected_decisions",
        {"decisions": decisions, "feedback": feedback},
        known=bool(decisions or feedback), evidence="DirectorContext.decisions/feedback or memory_state.unresolved_decisions",
        reason="Решения и обратная связь пользователя не загружены.")
    video_tasks = metadata.get("video_preparation_tasks")
    if video_tasks is None:
        video_tasks = [
            _record_payload(item) for item in actions
            if any(token in (_record_kind(item) + " " + str(_record_payload(item).get("description") or "").lower())
                   for token in ("video", "script", "thumbnail", "production", "подготов", "сценар", "облож"))
        ] or None
    put("video_preparation_tasks", video_tasks, known=video_tasks is not None,
        evidence="metadata.video_preparation_tasks or persisted actions matched to video-production work",
        reason="В истории действий нет записей подготовки видео, а отдельный реестр задач не подключён.")
    changed_conclusions = metadata.get("changed_conclusions")
    if changed_conclusions is None:
        changed_conclusions = _typed_records(results, "changed_conclusion", "conclusion_revision", "reassessment") or None
    put("changed_conclusions", changed_conclusions, known=changed_conclusions is not None,
        evidence="metadata.changed_conclusions or typed persisted conclusion revisions",
        reason="Нет реестра выводов, пересмотренных из-за новых данных.")

    # Resources and constraints. Do not treat estimated environment-based quota
    # as confirmed unified-manager quota.
    manager_quota = _dict(health.get("quota_manager"))
    if manager_quota.get("status") in {"healthy", "available", "unavailable", "degraded"}:
        put("unified_quota", manager_quota, known=True, evidence="runtime_health.quota_manager")
    else:
        put("unified_quota", quota if quota.get("accounting") == "unified_quota_manager" else None,
            known=quota.get("accounting") == "unified_quota_manager",
            evidence="project_state.quota",
            reason="Снимок содержит только оценку по inventory/env, а не подтверждённое чтение единого менеджера квоты.")
    free_tools = metadata.get("free_tools")
    put("free_tools", free_tools, known=free_tools is not None, evidence="metadata.free_tools",
        reason="Нет актуального реестра инструментов, стоимости и доступности.")
    restrictions = metadata.get("source_restrictions")
    if restrictions is not None:
        put("source_restrictions", restrictions, known=True, evidence="metadata.source_restrictions")
    else:
        put("source_restrictions", {"constraints": constraints, "source_health": health.get("youtube_sources")},
            known=bool(constraints or health.get("youtube_sources")),
            evidence="DirectorContext.constraints/runtime_health.youtube_sources",
            reason="Нет единого списка ограничений и ошибок источников.")
    budget = metadata.get("production_budget_mode")
    if budget is None:
        budget = health.get("production_budget_mode")
    budget_mode = budget.get("mode") if isinstance(budget, dict) else budget
    valid_budget_modes = {"zero", "minimal", "medium", "high"}
    budget_is_known = budget_mode in valid_budget_modes
    put("production_budget_mode", budget, known=budget_is_known,
        evidence="metadata.production_budget_mode/runtime_health.production_budget_mode",
        reason="Нужен явный PRODUCTION_BUDGET_MODE: zero/minimal/medium/high; FREE_MODE относится только к режиму бесплатного ИИ и не является бюджетом производства.")
    pending_tasks = metadata.get("pending_user_tasks")
    if pending_tasks is None:
        pending_tasks = [
            _record_payload(item) for item in actions
            if _status_of(item) in {"awaiting_user", "needs_user", "blocked_on_user", "waiting_for_user", "user_input_required"}
        ] or None
    put("pending_user_tasks", pending_tasks, known=pending_tasks is not None, evidence="metadata.pending_user_tasks or persisted actions explicitly awaiting user input",
        reason="В истории действий нет явных статусов ожидания пользователя, отдельный реестр пользовательских задач не подключён.")
    end_of_day = metadata.get("end_of_day_plan")
    if end_of_day is None:
        end_of_day = _typed_records(results, "end_of_day_plan", "daily_plan", "production_plan") or None
    put("end_of_day_plan", end_of_day, known=end_of_day is not None, evidence="metadata.end_of_day_plan or typed persisted daily/production plan",
        reason="Нет сохранённого дневного плана с задачами, сроками и доступными ресурсами.")

    parameters = {
        key: {
            "id": number,
            "label": label,
            **entries.get(key, _entry(reason="Параметр не был собран конструктором снимка.")),
            "freshness": assess_freshness(
                entries.get(key, {}).get("value"),
                max_age_seconds=FRESHNESS_MAX_AGE_SECONDS[key],
            ),
        }
        for number, key, label in REQUIRED_PARAMETERS
    }
    missing = [
        key for key, value in parameters.items()
        if value["status"] not in {STATUS_KNOWN, STATUS_UNKNOWN, STATUS_NOT_APPLICABLE}
        or (value["status"] == STATUS_UNKNOWN and not value.get("reason"))
        or (value["status"] == STATUS_NOT_APPLICABLE and not value.get("reason"))
    ]
    return {
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
        "generated_at": now,
        "project_id": getattr(context, "project_id", None),
        "completeness": {
            "required_count": len(REQUIRED_PARAMETERS),
            "represented_count": len(parameters),
            "known_count": sum(item["status"] == STATUS_KNOWN for item in parameters.values()),
            "unknown_count": sum(item["status"] == STATUS_UNKNOWN for item in parameters.values()),
            "not_applicable_count": sum(item["status"] == STATUS_NOT_APPLICABLE for item in parameters.values()),
            "invalid_count": len(missing),
            "valid": not missing,
            "invalid_parameters": missing,
        },
        "parameters": parameters,
    }


def validate_unified_state_snapshot(snapshot: Any) -> list[str]:
    """Return validation errors; an absent parameter or unexplained unknown fails."""
    errors: list[str] = []
    if not isinstance(snapshot, dict):
        return ["snapshot must be a dict"]
    parameters = snapshot.get("parameters")
    if not isinstance(parameters, dict):
        return ["parameters must be a dict"]
    expected = {key for _, key, _ in REQUIRED_PARAMETERS}
    for key in sorted(expected - set(parameters)):
        errors.append(f"{key}: missing required parameter")
    for key in sorted(set(parameters) - expected):
        errors.append(f"{key}: unexpected parameter")
    for key in sorted(expected & set(parameters)):
        entry = parameters[key]
        if not isinstance(entry, dict):
            errors.append(f"{key}: entry must be a dict")
            continue
        status = entry.get("status")
        if status not in {STATUS_KNOWN, STATUS_UNKNOWN, STATUS_NOT_APPLICABLE}:
            errors.append(f"{key}: missing or invalid status")
        elif status == STATUS_UNKNOWN and not str(entry.get("reason") or "").strip():
            errors.append(f"{key}: unknown status requires a reason")
        elif status == STATUS_NOT_APPLICABLE and not str(entry.get("reason") or "").strip():
            errors.append(f"{key}: not_applicable status requires a reason")
        elif status == STATUS_KNOWN and "value" not in entry:
            errors.append(f"{key}: known status requires a value field")
    return errors
