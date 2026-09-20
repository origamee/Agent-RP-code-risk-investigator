from worker.reasoning import parse_change_summary


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