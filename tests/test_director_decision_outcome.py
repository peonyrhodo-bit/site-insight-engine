import pytest

from director.decision import DecisionType, build_decision, decide_from_opportunity
from director.director import Director
import server
from server import _decision_to_memory_payload


@pytest.mark.parametrize(
    ("opportunity", "expected_type"),
    [
        (
            {"overall_score": 0.2, "confidence": 0.8, "applicability": 0.4},
            DecisionType.WAIT,
        ),
        (
            {"overall_score": 0.6, "confidence": 0.8, "applicability": 0.5},
            DecisionType.ANALYZE,
        ),
        (
            {"overall_score": 0.8, "confidence": 0.9, "applicability": 0.8},
            DecisionType.TEST,
        ),
        (
            {
                "overall_score": 0.8,
                "confidence": 0.9,
                "applicability": 0.8,
                "missing_data": ["динамика спроса"],
            },
            DecisionType.RESEARCH,
        ),
    ],
)
def test_opportunity_decision_has_expected_outcome(opportunity, expected_type):
    decision = decide_from_opportunity(opportunity)

    assert decision.decision_type is expected_type
    assert decision.next_action
    assert decision.rationale
    assert decision.expected_outcome


@pytest.mark.asyncio
async def test_no_opportunities_research_decision_has_expected_outcome():
    director = Director(project_id="test-project")

    decision = await director.decide({"opportunities": []})

    assert decision.decision_type is DecisionType.RESEARCH
    assert decision.next_action
    assert decision.rationale
    assert decision.expected_outcome


def test_expected_outcome_is_preserved_in_memory_payload():
    decision = build_decision(
        decision_type=DecisionType.TEST,
        objective="Проверить направление",
        rationale="Есть подтверждённые положительные сигналы.",
        confidence=0.8,
        next_action="Провести ограниченный тест.",
        expected_outcome="Получить измеримые результаты и сравнить их с критериями.",
    )

    payload = _decision_to_memory_payload(decision, project_id="test-project")

    assert payload["expected_outcome"] == (
        "Получить измеримые результаты и сравнить их с критериями."
    )
    assert payload["rationale"] == "Есть подтверждённые положительные сигналы."
    assert payload["next_action"] == "Провести ограниченный тест."
    assert payload["project_id"] == "test-project"



@pytest.mark.asyncio
async def test_expected_outcome_is_saved_with_decision():
    class FakeMemory:
        def __init__(self):
            self.saved = None

        def save_decision(self, *, decision, data, run_id=None):
            self.saved = {
                "decision": decision,
                "data": data,
                "run_id": run_id,
            }
            return 77

    memory = FakeMemory()
    adapter = object.__new__(server.ServerMemory)
    adapter.memory = memory
    decision = build_decision(
        decision_type=DecisionType.RESEARCH,
        objective="Исследовать направление",
        rationale="Не хватает данных.",
        confidence=0.3,
        next_action="Провести исследование YouTube.",
        expected_outcome="Получить проверяемые данные и закрыть пробелы.",
    )

    saved_id = await adapter.save_decision(
        project_id="test-project",
        decision=decision,
        run_id=12,
    )

    assert saved_id == 77
    assert memory.saved["run_id"] == 12
    assert memory.saved["data"]["expected_outcome"] == (
        "Получить проверяемые данные и закрыть пробелы."
    )
    assert memory.saved["data"]["rationale"] == "Не хватает данных."
    assert memory.saved["data"]["next_action"] == "Провести исследование YouTube."
