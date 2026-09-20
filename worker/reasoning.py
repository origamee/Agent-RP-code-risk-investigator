import json
import os
import requests

from dataclasses import dataclass
#this will standardize the result coming back from the model, in the following format
#binging the answer coming back from the LLM to this contract
#ChangeSummary = model's structured understanding of the diff.
#RiskAssessment = model's final judgment about that change.
@dataclass
class RiskAssessment:
    summary: str
    risk: str          # low | medium | high
    confidence: float  # 0.0 - 1.0
    reason: str

@dataclass
class ChangeSummary:
    summary: str
    changed_areas: list[str]
    security_relevant: bool


OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
MODEL = "llama3.2:3b"

def call_model(prompt: str) -> str:
    response = requests.post(
        f"{OLLAMA_URL}/api/chat",
        json={
            "model": MODEL,
            "messages": [
                {"role": "user", "content": prompt}
            ],
            "stream": False,
        },
        timeout=60,
    )

    response.raise_for_status()
    return response.json()["message"]["content"]

#Tihs will turn unreliable model text from extract_changes() below into a validated application object.
def parse_change_summary(raw: str) -> ChangeSummary:
    start = raw.find("{")
    end = raw.rfind("}") + 1

    if start == -1 or end == 0:
        raise ValueError("No JSON object found in model response")

    data = json.loads(raw[start:end])

    if not isinstance(data.get("summary"), str):
        raise ValueError("Invalid summary")

    if not isinstance(data.get("changed_areas"), list):
        raise ValueError("Invalid changed_areas")

    if not isinstance(data.get("security_relevant"), bool):
        raise ValueError("Invalid security_relevant")

    return ChangeSummary(
        summary=data["summary"],
        changed_areas=data["changed_areas"],
        security_relevant=data["security_relevant"],
    )

def extract_changes(diff: str) -> str:
#multi step reasoning i.e. understand first, judge second
    prompt = f"""
You are reviewing a Git code diff.

Identify the material behavior changes in the code.
Do not assess risk yet.

Return JSON with:
{{
  "summary": "short description",
  "changed_areas": ["area1", "area2"],
  "security_relevant": true
}}

DIFF:
{diff}
"""

    return call_model(prompt)

#this is validation rety number 1, retry once with stricter instructions
#updated to protect the retry as well this time
def generate_validated_change_summary(diff: str) -> ChangeSummary:
    raw = extract_changes(diff)

    try:
        return parse_change_summary(raw)

    except (ValueError, json.JSONDecodeError):
        retry_prompt = f"""
Your previous response was invalid.

Return ONLY valid JSON in this exact structure:

{{
  "summary": "short description",
  "changed_areas": ["area1", "area2"],
  "security_relevant": true
}}

DIFF:
{diff}
"""

        try:
            retry_raw = call_model(retry_prompt)
            return parse_change_summary(retry_raw)

        except (ValueError, json.JSONDecodeError):
            return ChangeSummary(
                summary="Model output could not be parsed",
                changed_areas=[],
                security_relevant=True, #conservative approach. If the model fails
                #we don't want to assume it's safe. Better to be cautious and flag it for review.
            )

#this step determines the risk level of the change based(step 1) on the diff and the structured summary from the model.
def assess_risk(diff: str, change_summary: ChangeSummary) -> str:
    prompt = f"""
You are a senior application security reviewer.

Here is the structured summary of what changed:
{change_summary}

Review the actual diff and assess the risk.

Return ONLY JSON:

{{
  "summary": "short risk summary",
  "risk": "low|medium|high",
  "confidence": 0.0,
  "reason": "why"
}}

DIFF:
{diff}
"""
    return call_model(prompt)

#Similar as we did for extraction, now parsing
def parse_risk_assessment(raw: str) -> RiskAssessment:
    start = raw.find("{")
    end = raw.rfind("}") + 1

    if start == -1 or end == 0:
        raise ValueError("No JSON object found")

    data = json.loads(raw[start:end])

    risk = data["risk"].strip().lower()
    confidence = float(data["confidence"])

    if risk not in {"low", "medium", "high"}:
        raise ValueError("Invalid risk label")

    if not 0.0 <= confidence <= 1.0:
        raise ValueError("Invalid confidence")

    return RiskAssessment(
        summary=data["summary"],
        risk=risk,
        confidence=confidence,
        reason=data["reason"],
    )

def generate_validated_risk_assessment(
    diff: str,
    change_summary: ChangeSummary
) -> RiskAssessment:

    raw = assess_risk(diff, change_summary)

    try:
        return parse_risk_assessment(raw)

    except (ValueError, json.JSONDecodeError, KeyError):
        retry_raw = assess_risk(diff, change_summary)

        try:
            return parse_risk_assessment(retry_raw)

        except (ValueError, json.JSONDecodeError, KeyError):
            return RiskAssessment(
                summary="Risk assessment could not be parsed",
                risk="medium",
                confidence=0.0,
                reason="Model failed to return valid structured output",
            )