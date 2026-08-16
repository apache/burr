# PostgreSQL Persistence with Ray

This guide explains how to use PostgreSQL persistence with Burr applications running on Ray workers.

## Overview

When running Burr applications on Ray workers, you can checkpoint state to PostgreSQL after each step. This enables:

- **Fault tolerance**: Resume from last checkpoint if a worker fails
- **State inspection**: Query application state from the database
- **Debugging**: Load and replay specific application states
- **Multi-instance coordination**: Share state across multiple Ray workers

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  Main Process                                                │
│  - Submits applications to Ray workers                       │
│  - Configures PostgreSQL connection                          │
└─────────────────────────────────────────────────────────────┘
                          │
                          │ Ray Remote Function
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│  Ray Worker (Application Execution)                          │
│                                                               │
│  ┌─────────────────────────────────────────────────────┐   │
│  │  Burr Application                                     │   │
│  │  - Executes workflow                                   │   │
│  │  - State management                                    │   │
│  └─────────────────────────────────────────────────────┘   │
│                          │                                   │
│                          │ After each step                   │
│                          ▼                                   │
│  ┌─────────────────────────────────────────────────────┐   │
│  │  PostgreSQLPersister                                  │   │
│  │  - Saves state to PostgreSQL                          │   │
│  │  - Uses state.serialize() for serde                   │   │
│  └─────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
                          │
                          │ SQL INSERT
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│  PostgreSQL Database                                         │
│                                                               │
│  Table: burr_state                                           │
│  - partition_key (TEXT)                                      │
│  - app_id (TEXT)                                             │
│  - sequence_id (INTEGER)                                     │
│  - position (TEXT)                                           │
│  - state (JSONB)                                             │
│  - status (TEXT)                                              │
│  - created_at (TIMESTAMP)                                    │
└─────────────────────────────────────────────────────────────┘
```

## Setup

### 1. Install Dependencies

```bash
pip install "burr[postgresql]"
```

### 2. Start PostgreSQL

Using Docker:

```bash
docker run --name local-psql \
  -v local_psql_data:/var/lib/postgresql/data \
  -p 5432:5432 \
  -e POSTGRES_PASSWORD=postgres \
  -d postgres
```

Or use an existing PostgreSQL instance.

### 3. Configure Connection

Set environment variables:

```bash
export USE_PERSISTENCE=true
export POSTGRES_HOST=localhost
export POSTGRES_PORT=5432
export POSTGRES_DB=postgres
export POSTGRES_USER=postgres
export POSTGRES_PASSWORD=postgres
export POSTGRES_TABLE=burr_state  # Optional, defaults to burr_state
```

Or configure in code:

```python
db_config = {
    "db_name": "postgres",
    "user": "postgres",
    "password": "postgres",
    "host": "localhost",
    "port": 5432,
    "table_name": "burr_state",
}
```

## Usage

### Basic Example

```python
from burr.integrations.persisters.b_psycopg2 import PostgreSQLPersister

# Create persister
persister = PostgreSQLPersister.from_values(
    db_name="postgres",
    user="postgres",
    password="postgres",
    host="localhost",
    port=5432,
    table_name="burr_state",
)

# Initialize table
persister.initialize()

# Build application with persistence
app = (
    ApplicationBuilder()
    .with_actions(...)
    .with_state_persister(persister)  # Auto-saves after each step
    .with_identifiers(app_id="my_app", partition_key="partition_1")
    .build()
)
```

### With Ray Workers

See `app_on_ray_worker_with_persistence.py` for a complete example:

```python
@ray.remote
def run_burr_application_on_worker(
    initial_state: dict,
    app_id: str,
    partition_key: str,
    db_config: Optional[Dict[str, Any]],
    ...
):
    # Create persister on Ray worker
    if db_config:
        persister = PostgreSQLPersister.from_values(**db_config)
        if not persister.is_initialized():
            persister.initialize()

    # Build application with persistence
    builder = ApplicationBuilder()...

    if persister:
        builder = builder.with_state_persister(persister)

    app = builder.build()

    # State is automatically saved after each step
    while True:
        action, result, state = app.step()
        # State checkpointed automatically!
        ...
```

## Resuming from Saved State

To resume an application from a saved checkpoint:

```python
# Build application with initialize_from
app = (
    ApplicationBuilder()
    .with_actions(...)
    .with_state_persister(persister)
    .initialize_from(
        persister,
        resume_at_next_action=True,  # Resume from last checkpoint
        default_state={"count": 0},  # Used if no saved state
        default_entrypoint="start_action",
    )
    .with_identifiers(app_id="my_app", partition_key="partition_1")
    .build()
)
```

The `initialize_from()` method:
- Loads the latest saved state for the given `app_id` and `partition_key`
- Resumes execution from the next action after the last checkpoint
- Falls back to `default_state` if no saved state exists

## State Serialization

The PostgreSQL persister uses Burr's built-in serialization:

- **Saving**: `state.serialize()` converts State to JSON-serializable dict
- **Loading**: `State.deserialize()` reconstructs State from dict
- **Custom serde**: Use `register_field_serde()` for non-serializable objects

Example with custom serde:

```python
from burr.core.serde import register_field_serde

# Register custom serializer for DB client
def serialize_db_client(client):
    return {"connection_string": client.connection_string}

def deserialize_db_client(data):
    return DummyDBClient(data["connection_string"])

register_field_serde("db_client", serialize_db_client, deserialize_db_client)

# Now DB clients in state will be properly serialized/deserialized
```

## Connection Management in Ray

### Important Considerations

1. **Connection per Worker**: Each Ray worker creates its own PostgreSQL connection
   - Connections are not shared across workers
   - Each worker manages its own connection lifecycle

2. **Connection Cleanup**: Always close connections properly
   ```python
   try:
       # Use persister
       ...
   finally:
       persister.cleanup()  # Close connection
   ```

3. **Connection Pooling**: For high-throughput scenarios, consider:
   - Using `AsyncPostgreSQLPersister` with connection pooling
   - Sharing a connection pool across applications on the same worker
   - Using a connection pool manager

4. **Serialization**: PostgreSQL connections cannot be serialized
   - Create persister on the Ray worker (not in main process)
   - Use `from_values()` to create connections on the worker
   - Don't pass connection objects to Ray remote functions

### Example: Connection Pool Manager

```python
class PersisterPool:
    """Manages PostgreSQL persisters for Ray workers"""

    def __init__(self, db_config: dict):
        self.db_config = db_config
        self._persisters = {}

    def get_persister(self, worker_id: str):
        """Get or create persister for a worker"""
        if worker_id not in self._persisters:
            persister = PostgreSQLPersister.from_values(**self.db_config)
            if not persister.is_initialized():
                persister.initialize()
            self._persisters[worker_id] = persister
        return self._persisters[worker_id]
```

## Querying Saved State

You can query saved state directly from PostgreSQL:

```sql
-- Get latest state for an application
SELECT state, sequence_id, position, created_at
FROM burr_state
WHERE app_id = 'my_app' AND partition_key = 'partition_1'
ORDER BY sequence_id DESC
LIMIT 1;

-- List all applications
SELECT DISTINCT app_id, partition_key, MAX(sequence_id) as last_sequence
FROM burr_state
GROUP BY app_id, partition_key;

-- Get state at specific sequence_id
SELECT state, position, status
FROM burr_state
WHERE app_id = 'my_app'
  AND partition_key = 'partition_1'
  AND sequence_id = 5;
```

Or use the persister API:

```python
# Load latest state
data = persister.load(partition_key="partition_1", app_id="my_app")
if data:
    state = data["state"]
    sequence_id = data["sequence_id"]
    position = data["position"]

# List all app IDs
app_ids = persister.list_app_ids(partition_key="partition_1")
```

## Best Practices

1. **Unique App IDs**: Use unique `app_id` for each application instance
   ```python
   app_id = f"app_{uuid.uuid4()}"  # or timestamp-based
   ```

2. **Partition Keys**: Use partition keys to organize applications
   ```python
   partition_key = f"user_{user_id}"  # Per-user partitioning
   ```

3. **Error Handling**: Handle connection errors gracefully
   ```python
   try:
       persister = PostgreSQLPersister.from_values(...)
   except Exception as e:
       logger.warning(f"Failed to connect to PostgreSQL: {e}")
       # Continue without persistence or retry
   ```

4. **Cleanup**: Always close connections
   ```python
   try:
       # Use persister
   finally:
       persister.cleanup()
   ```

5. **Monitoring**: Monitor checkpoint frequency and database size
   - Each step creates a new checkpoint
   - Consider cleanup strategies for old checkpoints
   - Monitor database growth

## Troubleshooting

### Connection Errors

**Problem**: `psycopg2.OperationalError: could not connect to server`

**Solutions**:
- Verify PostgreSQL is running: `docker ps` or `pg_isready`
- Check connection parameters (host, port, password)
- Ensure network connectivity from Ray workers to PostgreSQL
- Check firewall rules

### Serialization Errors

**Problem**: `TypeError: Object of type X is not JSON serializable`

**Solutions**:
- Use `register_field_serde()` for custom types
- Ensure all state values are serializable
- Check that `state.serialize()` works before persistence

### Table Not Found

**Problem**: `relation "burr_state" does not exist`

**Solutions**:
- Call `persister.initialize()` to create the table
- Check table name matches configuration
- Verify database permissions

### State Not Loading

**Problem**: `initialize_from()` doesn't find saved state

**Solutions**:
- Verify `app_id` and `partition_key` match saved state
- Check that state was actually saved (check database)
- Ensure `resume_at_next_action=True` is set

## Example: Complete Workflow

```python
import os
import ray
from burr.integrations.persisters.b_psycopg2 import PostgreSQLPersister

@ray.remote
def run_app_with_persistence(app_id: str, initial_state: dict):
    # Create persister on worker
    db_config = {
        "db_name": os.getenv("POSTGRES_DB", "postgres"),
        "user": os.getenv("POSTGRES_USER", "postgres"),
        "password": os.getenv("POSTGRES_PASSWORD", "postgres"),
        "host": os.getenv("POSTGRES_HOST", "localhost"),
        "port": int(os.getenv("POSTGRES_PORT", "5432")),
    }

    persister = PostgreSQLPersister.from_values(**db_config)
    if not persister.is_initialized():
        persister.initialize()

    # Build and run application
    app = (
        ApplicationBuilder()
        .with_actions(...)
        .with_state_persister(persister)
        .with_identifiers(app_id=app_id, partition_key="demo")
        .with_state(**initial_state)
        .build()
    )

    try:
        # Execute - state auto-saved after each step
        while True:
            action, result, state = app.step()
            if app.get_next_action() is None:
                break
    finally:
        persister.cleanup()

    return app.state.get_all()

# Run on Ray
ray.init()
future = run_app_with_persistence.remote("app_1", {"count": 0})
result = ray.get(future)
```

## See Also

- [State Persistence Documentation](../../docs/concepts/state-persistence.rst)
- [PostgreSQL Persister Reference](../../docs/reference/persister.rst)
- [State Serialization Guide](README.md#state-serialization)
