import json
import os
import threading
import uuid
from collections import deque

from confluent_kafka import Consumer
from fastapi import FastAPI

app = FastAPI(title="Code Risk Results")

results = deque(maxlen=50)

BROKERS = os.getenv("REDPANDA_BROKERS", "localhost:19092")


def consume_results():
    consumer = Consumer({
        "bootstrap.servers": BROKERS,
        "group.id": f"results-api-{uuid.uuid4()}",
        "auto.offset.reset": "earliest",
        "enable.auto.commit": False,
    })

    consumer.subscribe(["code-risk-results"])

    while True:
        msg = consumer.poll(1.0)

        if msg is None:
            continue

        if msg.error():
            continue

        results.append(
            json.loads(msg.value().decode("utf-8"))
        )


@app.on_event("startup")
def start_consumer():
    thread = threading.Thread(
        target=consume_results,
        daemon=True,
    )
    thread.start()


@app.get("/results")
def get_results():
    return list(results)