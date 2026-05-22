# Durable Execution: Human-in-the-Loop

This example demonstrates Burr's suspend/resume primitives through a three-step
draft-review-finalize workflow. The `review` action suspends the workflow and
waits for a human to approve or reject a draft. While suspended, the process can
die and restart without losing progress — the `durable()` call memoizes expensive
sub-steps (like an LLM summary) in a journal, so they are not re-executed on
resume.

The same pattern covers three production use-cases: human-in-the-loop approval
gates, waiting for an external event (webhook, queue message, IoT sensor), and
crash resilience where a long-running action is interrupted mid-flight.

## How to run

```bash
pip install burr
python application.py
```

The script runs the workflow to the `review` suspension, prints the suspended
channel and metadata, then immediately simulates the human responding with
`{"approved": True}` via `resume()` and prints the final state.

## The `human_approval` channel

In production you would expose the `resume()` call through a webhook or UI
button. When the workflow suspends, store the `app_id` and `partition_key`
alongside the suspension metadata (returned by `app.suspended.metadata`). Your
webhook handler then calls:

```python
from burr.core import resume
from burr.core.persistence import SQLitePersister

persister = SQLitePersister.from_values("durable.db")
persister.initialize()
final_state = resume(
    persister=persister,
    graph=graph,        # same Graph object (or rebuild it)
    app_id=app_id,
    partition_key=partition_key,
    channel="human_approval",
    payload={"approved": True},
)
```

## Further reading

- [Durable Execution concepts](../../docs/concepts/durable-execution.rst) (landing in Task 6.2)
- [Burr documentation](https://burr.dagworks.io)
