from worker.reasoning import parse_change_summary
from worker.reasoning import RiskAssessment, route_decision

def test_parse_change_summary_with_extra_text():
    raw = """
    Here is the JSON response:

    {
      "summary": "Authentication logic changed",
      "changed_areas": ["auth", "tokens"],
      "security_relevant": true
    }
    """

    result = parse_change_summary(raw)

    assert result.summary == "Authentication logic changed"
    assert result.changed_areas == ["auth", "tokens"]
    assert result.security_relevant is True


def test_route_decision():
    low_confidence = RiskAssessment(
        summary="uncertain",
        risk="low",
        confidence=0.2,
        reason="model uncertain",
    )

    high_risk = RiskAssessment(
        summary="dangerous change",
        risk="high",
        confidence=0.9,
        reason="security-sensitive change",
    )

    normal = RiskAssessment(
        summary="routine change",
        risk="low",
        confidence=0.9,
        reason="low-risk change",
    )

    assert route_decision(low_confidence) == "needs_human_review"
    assert route_decision(high_risk) == "urgent_review"
    assert route_decision(normal) == "normal"