import json
import requests
import os
from dotenv import load_dotenv
from confluent_kafka import Consumer, Producer
from dataclasses import asdict
from reasoning import (
    generate_validated_change_summary,
    generate_validated_risk_assessment,
)

load_dotenv("../.env")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")

MAX_DIFF_CHARS = 12000 #binding the diff before we send it to an LLM

def prepare_diff(diff):
    if len(diff) <= MAX_DIFF_CHARS:
        return diff

    return diff[:MAX_DIFF_CHARS] + "\n\n[DIFF TRUNCATED]"

consumer = Consumer({
    "bootstrap.servers": "localhost:19092",
    "group.id": "code-risk-worker",
    "auto.offset.reset": "earliest",
})

producer = Producer({
    "bootstrap.servers": "localhost:19092"
})

def fetch_diff(event):
    repo = event["repo_name"]
    before = event["before_sha"]
    head = event["head_sha"]

    # New branch: GitHub uses all-zero "before" SHA
    if before == "0" * 40:
        print(f"Skipping new-branch event: {repo}")
        return None

    url = f"https://api.github.com/repos/{repo}/compare/{before}...{head}"

    try:
        response = requests.get(
            url,
            headers={
                "User-Agent": "redpanda-fde-exercise",
                "Accept": "application/vnd.github.v3.diff",
                "Authorization": f"Bearer {GITHUB_TOKEN}",
            },
            timeout=10,
        )

        if response.status_code == 404:
            print(f"Diff unavailable, skipping: {repo}")
            return None

        response.raise_for_status()
        return response.text

    except requests.RequestException as e:
        print(f"GitHub fetch failed: {e}")
        return None

consumer.subscribe(["github-push-events"])

print("Waiting for GitHub push events...")

while True:
    msg = consumer.poll(1.0)

    if msg is None:
        continue

    if msg.error():
        print(msg.error())
        continue

    event = json.loads(msg.value().decode("utf-8"))
    diff = fetch_diff(event)
    if not diff:
        continue

    diff = prepare_diff(diff) #binded diff composition
    print("\nReceived:")
    print(json.dumps(event, indent=2)) #show the event

    print(f"\nDiff size sent for reasoning: {len(diff)} characters")

    print("\nActual code diff:")
    print(diff[:3000]) #bind the diff

    change_summary = generate_validated_change_summary(diff) #this function will call the 
    #raw extract_text internally and then validates/retries the output
    
    #Now this will call the risk orchestrator similar to change orchestrator in the previous step
    risk_assessment = generate_validated_risk_assessment(
    diff,
    change_summary,
    )
    
    print("\nStep 1 - Change Summary:")
    print(change_summary)

    print("\nStep 2 - Risk Assessment:")
    print(risk_assessment)

    #now this is what I added after looking at real risk assessment output. 
    #I'd say a kind of confidence based branching
    if risk_assessment.confidence < 0.6:
        decision = "needs_human_review"
    elif risk_assessment.risk == "high":
        decision = "urgent_review"
    else:
        decision = "normal"

    print(f"\nDecision: {decision}")

    #Now publishing a reusable structured result back into Redpanda.
    result = {
    "event_id": event["event_id"],
    "repo_name": event["repo_name"],
    "change_summary": asdict(change_summary),
    "risk_assessment": asdict(risk_assessment),
    "decision": decision,
}

    producer.produce(
        "code-risk-results",
        key=event["event_id"],
        value=json.dumps(result),
    )

    producer.flush()