import json
import requests
import os
from dotenv import load_dotenv
from confluent_kafka import Consumer

load_dotenv("../.env")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")

consumer = Consumer({
    "bootstrap.servers": "localhost:19092",
    "group.id": "code-risk-worker",
    "auto.offset.reset": "earliest",
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

    print("\nActual code diff:")
    print(diff[:3000])

    print("\nReceived:")
    print(json.dumps(event, indent=2))