# Redpanda Code Risk Investigator

A local event-driven system that consumes public GitHub push events, fetches the actual code diff, performs multi-step LLM reasoning on each change, routes the result based on risk and confidence, and exposes recent results through a JSON API.

## Architecture

```text
GitHub Public Events API
        |
        v
Redpanda Connect
- polls public events
- keeps PushEvent records
- projects required fields
- deduplicates events
        |
        v
github-push-events
        |
        v
Python Reasoning Worker
- fetches the GitHub compare diff
- bounds diff size
- Step 1: change extraction
- validates and retries malformed model output
- Step 2: risk assessment
- validates, retries, and falls back conservatively
- confidence-based routing
        |
        v
code-risk-results
        |
        v
FastAPI
GET /results
```

## What Runs in Redpanda Connect vs. Python

Redpanda Connect handles the data plumbing: polling the public source, filtering to push events, projecting the event shape, deduplicating, and writing to Redpanda.

The Python worker handles enrichment and reasoning: fetching content that is not present in the original feed, calling the local model, validating model output, retrying malformed output, making the routing decision, and publishing the structured result.

## Requirements

- Docker
- Docker Compose

Optional:

- GitHub Personal Access Token

The source feed is public and works without signup. A GitHub token is optional, but it reduces the chance of anonymous API rate limiting when the worker fetches commit diffs.

## Configuration

The system can run without a token.

If you want to use a GitHub token:

```bash
cp .env.example .env
```

Then edit `.env`:

```text
GITHUB_TOKEN=your_token_here
```

Do not commit `.env`.

## Run

From the repository root:

```bash
docker compose up --build
```

On first startup, Docker Compose will also pull the local Ollama model (`llama3.2:3b`). This can take several minutes depending on network speed. Later runs reuse the downloaded model volume.

Compose starts:

1. Redpanda
2. A topic-init container that creates the required topics
3. Redpanda Connect
4. Ollama
5. An Ollama init container that ensures the model is present
6. The Python reasoning worker
7. The FastAPI results service

## View Results

Open:

```text
http://localhost:8000/results
```

or:

```bash
curl http://localhost:8000/results
```

The endpoint returns the most recent processed results. It may initially return an empty list until a GitHub `PushEvent` is received and processed.

Each result contains:

- GitHub event ID
- repository name
- structured change summary
- risk assessment
- model confidence
- routing decision

Possible routing decisions:

```text
normal
needs_human_review
urgent_review
```

## Inspect Redpanda Topics

```bash
docker exec redpanda-code-risk-investigator-redpanda-1 rpk topic list
```

Expected topics:

```text
github-push-events
code-risk-results
```

If Docker Compose chooses a different project/container prefix, use:

```bash
docker compose ps
```

to find the Redpanda container name.

## Stop

```bash
docker compose down
```

The Ollama model is stored in a named Docker volume and is reused on later runs.

## Reasoning Flow

### Step 1: Change Extraction

The worker sends the actual Git diff to the model and asks for a structured description of the material code changes.

Expected shape:

```json
{
  "summary": "short description",
  "changed_areas": ["area1", "area2"],
  "security_relevant": true
}
```

The response is parsed and validated. If the model returns malformed output, the worker retries with stricter formatting instructions. If the retry also fails, it returns a conservative fallback instead of crashing the worker.

### Step 2: Risk Assessment

The worker sends both the structured change summary and the actual diff to the model for a second reasoning step.

Expected shape:

```json
{
  "summary": "short risk summary",
  "risk": "low",
  "confidence": 0.8,
  "reason": "short explanation"
}
```

The response is validated and malformed output is retried.

Routing is confidence-first:

```text
confidence < 0.6  -> needs_human_review
high risk         -> urgent_review
otherwise         -> normal
```

A failed or low-confidence model response is therefore not silently treated as safe.

## Reliability and Failure Handling

The worker distinguishes between permanent and transient diff-enrichment failures.

- Permanent failures, such as a diff that cannot exist for a newly created branch or a 404, are intentionally skipped and committed.
- Transient GitHub/API failures are retried with bounded exponential backoff.
- If transient retries are exhausted, the worker exits without committing the input event, allowing Redpanda to replay it after restart.
- The worker commits the consumed event only after the result has been published successfully.
- Model transport failures and malformed model responses degrade to conservative structured output rather than taking down the processing loop.

## Tests

The tests focus on risky behavior rather than broad coverage.

From the repository root:

```bash
python3 -m venv worker/.venv
source worker/.venv/bin/activate
python -m pip install -r worker/requirements.txt
python -m pip install pytest
PYTHONPATH=. python -m pytest -q
```

The current tests verify:

- model output containing extra surrounding text can still be parsed
- confidence/risk routing produces the expected decision

Expected result:

```text
2 passed
```

## Project Structure

```text
.
├── connect/
│   └── connect.yaml
├── worker/
│   ├── app.py
│   ├── reasoning.py
│   ├── Dockerfile
│   └── requirements.txt
├── serve/
│   ├── app.py
│   ├── Dockerfile
│   └── requirements.txt
├── tests/
│   └── test_reasoning.py
├── docker-compose.yml
├── .env.example
├── .gitignore
├── .dockerignore
└── README.md
```

## Tradeoffs

### Tradeoff 1

**TODO — write this section in my own words.**

Cover:
- what decision I made
- what alternative I considered
- why I chose this design for the exercise
- when I would switch to the alternative

### Tradeoff 2

**TODO — write this section in my own words.**

Cover:
- what decision I made
- what alternative I considered
- why I chose this design for the exercise
- when I would switch to the alternative

## Surprises and Production Considerations

**TODO — write this section in my own words.**

Cover what I actually observed while building and running the system, plus what I would change for a production deployment.

Useful areas to consider:
- malformed local-model JSON
- poorly calibrated model confidence
- noisy/spam/non-code public GitHub events
- GitHub API rate limits
- large diff truncation
- stronger production observability
- scaling consumers by partition
- durable result storage or downstream materialization
- stronger model/evaluation strategy

## Why This Matters

**TODO — write 3–4 sentences in my own words for a nontechnical customer stakeholder.**