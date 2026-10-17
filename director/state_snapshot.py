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


def _status_of(item: Any) -> str:
    return str(_dict(item).get("status") or "").strip().lower()


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
            or item.get("created_at") or ""
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
    runs = _list(memory_state.get("recent_runs"))
    decisions = _list(getattr(context, "decisions", []))
    recommendations = _list(getattr(context, "recommendations", []))
    actions = _list(memory_state.get("unfinished_actions"))
    if not actions:
        actions = _list(memory_state.get("recent_actions"))
    events = _list(memory_state.get("recent_events"))
    research = _list(getattr(context, "research_history", []))
    if not research:
        research = _list(metadata.get("research_sets")) or _list(memory_state.get("recent_results"))
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

    run_status = str(_dict(last_cycle).get("status") or "").lower()
    active_statuses = {"requested", "registered", "running", "initializing", "in_progress"}
    if run_status in active_statuses or run_status in {"completed", "partial", "failed", "cancelled"}:
        put("concurrent_cycle", {"status": run_status, "cycle": _dict(last_cycle)},
            known=True, evidence="Director.last_cycle")
    else:
        active = _dict(health.get("active_cycle"))
        if active.get("status") in {"healthy", "available", "unavailable", "degraded"}:
            put("concurrent_cycle", active, known=True, evidence="runtime_health.active_cycle")
        else:
            put("concurrent_cycle", None, reason="Нет подтверждённого снимка блокировки/активных запусков.")

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
        put("result_reuse", None, reason="Не измерено, переиспользуются ли сохранённые результаты вместо повторных запросов.")

    topics = _dict(getattr(context, "topics", {}))
    coverage = _dict(project_state.get("coverage"))
    under_researched = metadata.get("under_researched_directions")
    put("under_researched_directions", under_researched,
        known=under_researched is not None, evidence="metadata.under_researched_directions",
        reason="Инвентарь тем и число запросов не показывают, какие именно направления недостаточно изучены.")

    hypothesis = metadata.get("current_hypothesis")
    hypotheses = metadata.get("hypotheses")
    put("hypotheses", hypotheses if hypotheses is not None else hypothesis,
        known=hypotheses is not None or isinstance(hypothesis, dict),
        evidence="metadata.hypotheses/current_hypothesis",
        reason="Нет устойчивого реестра гипотез со статусами проверки.")

    forecasts = metadata.get("forecasts")
    put("forecasts", forecasts, known=forecasts is not None, evidence="metadata.forecasts",
        reason="Нет реестра прогнозов и результатов их сравнения с фактами.")
    due = metadata.get("due_measurements")
    put("due_measurements", due, known=due is not None, evidence="metadata.due_measurements",
        reason="Нет вычисленного списка наступивших повторных измерений.")
    changes = metadata.get("new_data_since_last_cycle")
    if changes is not None:
        put("new_data_since_last_cycle", changes, known=True, evidence="metadata.new_data_since_last_cycle")
    else:
        put("new_data_since_last_cycle", None,
            evidence="project_state.freshness" if freshness else "",
            reason="Свежесть данных сама по себе не доказывает, какие данные появились после прошлого цикла; нет сравнения двух снимков.")

    put("created_recommendations", recommendations, known=bool(recommendations),
        evidence="DirectorContext.recommendations", reason="Рекомендации не загружены в контекст.")
    awaiting = [r for r in recommendations if _status_of(r) in {"new", "draft", "pending", "proposed"}]
    discussed = [r for r in recommendations if _status_of(r) in {"discussed", "under_discussion"}]
    put("recommendations_awaiting_user", awaiting, known=bool(recommendations),
        evidence="recommendation status values", reason="Нельзя определить очередь решений без загруженных рекомендаций.")
    put("recommendations_under_discussion", discussed, known=bool(recommendations),
        evidence="recommendation status values", reason="Нельзя определить обсуждаемые рекомендации без загруженных рекомендаций.")
    put("accepted_rejected_decisions",
        {"decisions": decisions, "feedback": feedback},
        known=bool(decisions or feedback), evidence="DirectorContext.decisions/feedback",
        reason="Решения и обратная связь пользователя не загружены.")
    video_tasks = metadata.get("video_preparation_tasks")
    put("video_preparation_tasks", video_tasks, known=video_tasks is not None,
        evidence="metadata.video_preparation_tasks",
        reason="Нет отдельного реестра задач подготовки видео и статусов.")
    changed_conclusions = metadata.get("changed_conclusions")
    put("changed_conclusions", changed_conclusions, known=changed_conclusions is not None,
        evidence="metadata.changed_conclusions",
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
    put("production_budget_mode", budget, known=budget is not None, evidence="metadata.production_budget_mode",
        reason="Режим бюджета производства не передан в контекст.")
    pending_tasks = metadata.get("pending_user_tasks")
    put("pending_user_tasks", pending_tasks, known=pending_tasks is not None, evidence="metadata.pending_user_tasks",
        reason="Нет полного списка задач, ожидающих пользователя.")
    end_of_day = metadata.get("end_of_day_plan")
    put("end_of_day_plan", end_of_day, known=end_of_day is not None, evidence="metadata.end_of_day_plan",
        reason="Нет расчёта дневного плана, сроков и доступных ресурсов.")

    parameters = {
        key: {
            "id": number,
            "label": label,
            **entries.get(key, _entry(reason="Параметр не был собран конструктором снимка.")),
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
