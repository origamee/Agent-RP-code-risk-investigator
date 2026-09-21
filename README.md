# Redpanda Code Risk Investigator

A local event-driven system that consumes public GitHub push events, fetches the actual code diff, performs multi-step LLM reasoning on each change, routes the result based on risk/confidence, and exposes recent results through a JSON API.

## Architecture

GitHub Public Events API
        |
        v
Redpanda Connect
- polls public events
- filters PushEvent
- projects required fields
- deduplicates events
        |
        v
github-push-events
        |
        v
Python Reasoning Worker
- fetches GitHub compare diff
- bounds diff size
- Step 1: change extraction
- validates model output
- retries malformed output
- Step 2: risk assessment
- validates/retries/fallback
- confidence-based routing
        |
        v
code-risk-results
        |
        v
FastAPI
GET /results

## Requirements

- Docker
- Docker Compose

Optional:

- GitHub Personal Access Token

The GitHub source is public and does not require signup. A token can be supplied to reduce anonymous API rate-limit issues.

## Configuration

Create a local `.env` file:

```bash
cp .env.example .env

## Tradeoffs

### Tradeoff 1
[Your paragraph: choice, alternative, why you chose it, when you'd switch.]

### Tradeoff 2
[Your paragraph: choice, alternative, why you chose it, when you'd switch.]

## Surprises and Production Considerations
[Your paragraph on malformed LLM JSON, model confidence, GitHub noise/rate limits, and what you'd improve in production.]

## Why This Matters
[3–4 sentences in your own words for a nontechnical customer.]