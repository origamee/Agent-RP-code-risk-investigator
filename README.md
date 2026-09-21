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

- Chose llama3.2:3b because of its strong performance-to-size ratio, fast local setup, Docker compatibility, and my familiarity with Ollama.
- It made the project reproducible and self-contained really quickly without me handling any external dependencies.
- Tradeoff: weaker model quality, more prompt/retry work, less reliable structured output, and less consistent confidence/accuracy.
- I’d switch to a larger or hosted model when production accuracy and consistency matter more than local simplicity/cost.

### Tradeoff 2

I had the choice for choosing either of the sources from GitHub, USGS earthquake data, Hacker News data, and Wikipedia recent changes, I chose GitHub. 

- The feed coming out of USGS was more structured than I wanted it to be, so I thought that running an LLM on an source that has already structured fields might make the reasoning layer behave more like classification rather than justified reasoning. And I believe the assignment actually warned against using some verbiage like "regex wearing a costume," so I stayed away from the USGS source due to these reasons. 
- HackerNews gives back a ton of links and then those need to be sifted through. And link handling can be a pain (we all remember beautiful soup and Selenium libraries so you can say I am biased). Examples are HTML, JS heavy pages, going through paywalls, files formats hosted on those pages etc. So I didn't want complexity to be in scraping the web, I'd rather deal with complexity in our actual mission which was -- event pipeline+reasoning.
- Wikipedia is a true SSE stream which brings a ton of framing, heartbeats, connection drop + reconnection logic, JSON lines terminated inefficiently etc
- With Github I had to still deal with a few challenges but I believe these issues were more inline with event pipeline gen i.e. foreign language changes, non-code repos, spam. I started with a non-authenticated feed but was dealing with API rate limiting for Github diff/enrichment type API calls. So switched to a feed with an API token and the rate limiting for this particular function went away mostly. But then I had to add filtering, dedupe, diff for enrichment, retry logic, permanent vs transient failure handling, bounded diff size, structured output validation, fallback behavior etc.
Once we processed everything, the model had to interpret something semantically meaningful
- So ultimately, I had something real through Github that the model can reason on i.e. "actual code diff"

## Surprises and Production Considerations

Here are are raw notes on somethings that I learned:

- Malformed LLM output was probably the biggest surprise. 
Even when I explicitly asked for JSON, the local model sometimes returned extra text, foreign-language content, or nothing parseable. That forced me to add extraction, schema validation, retry prompts, and a conservative fallback instead of trusting the model output in the end.
- Confidence was not really calibrated. 
I saw 0.8 confidence on conclusions that were clearly questionable, while very simple low-risk changes sometimes came back with 0.0. So confidence was useful for routing, but I would not treat the number as objectively meaningful without evaluation/calibration at the first pass, specially coming out of Ollama.
The public GitHub stream was much noisier than expected. I saw spam repos, README changes, generated content, foreign-language content, non-code changes, etc. In production I would probably add stronger pre-model filtering so I don’t spend model cycles on obviously irrelevant events.
- Rate limits became real very quickly. 
The public event stream was fine, but fetching diffs caused 403/429 behavior. Adding an optional GitHub token helped, and I then added retry/backoff plus permanent-vs-transient error handling.
- The worker originally crashed when the retry model call timed out. 
That was useful because it exposed that retry logic itself also has to be protected. I changed the model call to fail safely and added bounded output/token limits.
- Large diffs were another problem. 
Right now we truncate at 12,000 characters. That keeps latency and local-model load bounded, but obviously the security-relevant material could theoretically be beyond the cutoff. In production I would select important files/chunks rather than blindly cutting the string.
- Observability is minimal right now. 
For production I’d want metrics around events consumed, events skipped, LLM retries, parse failures, latency, GitHub failures, model failures, confidence distribution, and routing outcomes.
- Scaling: 
right now it’s effectively one reasoning worker. Redpanda gives us a natural scaling model by adding partitions and multiple workers in the same consumer group.
- Result storage: 
code-risk-results is enough for this exercise, and the FastAPI service keeps a recent in-memory view. For a real customer I’d likely materialize the results into something durable/queryable like Postgres or a search/analytics store while keeping Redpanda as the event backbone.

## Raw final thoughts

- Engineering teams generate more code changes than humans can deeply review.
- The system automatically enriches each change with the actual diff and uses AI to help identify which changes deserve attention.
- The important part is that uncertain results are escalated instead of quietly treated as safe.
- That lets human reviewers spend time on the changes most likely to matter, rather than manually inspecting everything.