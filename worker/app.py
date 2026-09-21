import time
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
from reasoning import (
    generate_validated_change_summary,
    generate_validated_risk_assessment,
    route_decision,
)

load_dotenv("../.env")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
BROKERS = os.getenv("REDPANDA_BROKERS", "localhost:19092")

MAX_DIFF_CHARS = 12000 #binding the diff before we send it to an LLM

class PermanentDiffUnavailable(Exception):
    pass
class TransientDiffError(Exception):
    pass

def prepare_diff(diff):
    if len(diff) <= MAX_DIFF_CHARS:
        return diff

    return diff[:MAX_DIFF_CHARS] + "\n\n[DIFF TRUNCATED]"

consumer = Consumer({
    "bootstrap.servers": BROKERS,
    "group.id": "code-risk-worker",
    "auto.offset.reset": "earliest",
    "enable.auto.commit": False,
})

producer = Producer({
    "bootstrap.servers": BROKERS
})

def fetch_diff(event):
    repo = event["repo_name"]
    before = event["before_sha"]
    head = event["head_sha"]

    if before == "0" * 40:
        raise PermanentDiffUnavailable("New branch has no previous commit to compare")

    url = f"https://api.github.com/repos/{repo}/compare/{before}...{head}"

    headers = {
        "User-Agent": "redpanda-code-risk-investigator",
        "Accept": "application/vnd.github.v3.diff",
    }

    if GITHUB_TOKEN:
        headers["Authorization"] = f"Bearer {GITHUB_TOKEN}"

    try:
        response = requests.get(url, headers=headers, timeout=10)

        if response.status_code == 404:
            raise PermanentDiffUnavailable(f"Diff unavailable for {repo}")

        if response.status_code in {403, 429} or response.status_code >= 500:
            raise TransientDiffError(
                f"GitHub temporary failure: HTTP {response.status_code}"
            )

        response.raise_for_status()
        return response.text

    except requests.RequestException as exc:
        raise TransientDiffError(str(exc)) from exc

def fetch_diff_with_retry(event, max_attempts=3):
    for attempt in range(1, max_attempts + 1):
        try:
            return fetch_diff(event)

        except PermanentDiffUnavailable:
            raise

        except TransientDiffError as exc:
            if attempt == max_attempts:
                raise

            delay = 2 ** (attempt - 1)

            print(
                f"Temporary GitHub failure "
                f"(attempt {attempt}/{max_attempts}): {exc}. "
                f"Retrying in {delay}s..."
            )

            time.sleep(delay)

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
    try:
        diff = fetch_diff_with_retry(event)

    except PermanentDiffUnavailable as exc:
        print(f"Permanent skip: {exc}")
        consumer.commit(message=msg, asynchronous=False)
        continue

    except TransientDiffError as exc:
        print(f"GitHub failure after retries: {exc}")
        raise

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
    #and now I've separated the decision routing into a separate function for clarity and running tests.
    decision = route_decision(risk_assessment)

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

    remaining = producer.flush(10)

    if remaining != 0:
        print(f"Publish failed: {remaining} message(s) undelivered")
        raise RuntimeError("Could not publish result")

    consumer.commit(message=msg, asynchronous=False)

    print(f"Committed event: {event['event_id']}")