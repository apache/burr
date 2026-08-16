"""
Example: Burr Application on Ray Worker with PostgreSQL Persistence

This demonstrates running an entire Burr application on a Ray worker with state
checkpointing to PostgreSQL. State is automatically saved after each step, enabling
resume from failures and state inspection.

Architecture:
- Main Process → Ray Worker (runs entire Burr application)
- Ray Worker → PostgreSQL (checkpoints state after each step)
- Ray Worker → Ray Actors (runs tagged actions, local execution for others)

Key features:
- State persistence to PostgreSQL after each step
- Resume from saved state
- Multiple applications with independent state tracking
- Proper connection management in Ray environment
"""

import os
import time
from typing import Any, Dict, Optional

import ray

from burr.core import Action, State, action
from burr.lifecycle import ActionExecutionInterceptorHook

# Try to import PostgreSQL persister
try:
    from burr.integrations.persisters.b_psycopg2 import PostgreSQLPersister
except ImportError:
    PostgreSQLPersister = None
    print(
        "Warning: PostgreSQL persister not available. Install with: pip install 'burr[postgresql]'"
    )


# ============================================================================
# Step 1: Define Ray Actors for Heavy Actions
# ============================================================================


@ray.remote
class SpecializedActor:
    """
    Actor that holds specialized resources for specific action types.
    For example: GPU for ML inference, database connection pool, etc.
    """

    def __init__(self, actor_id: int, specialization: str):
        self.actor_id = actor_id
        self.specialization = specialization
        print(f"[Actor {actor_id}] Initializing {specialization} resources...")
        time.sleep(0.5)  # Simulate expensive initialization
        self.resource = f"{specialization}_Resource_{actor_id}"
        self.request_count = 0
        print(f"[Actor {actor_id}] Ready for {specialization} tasks")

    def execute_action(self, action, state_dict: dict, inputs: dict) -> tuple:
        """Execute action using actor's specialized resources"""
        self.request_count += 1
        print(f"[Actor {self.actor_id}] Processing {action.name} with {self.specialization}")

        # Deserialize state on actor side
        state = State.deserialize(state_dict)

        # Execute the action
        if hasattr(action, "single_step") and action.single_step:
            result, new_state = action.run_and_update(state, **inputs)
        else:
            state_to_use = state.subset(*action.reads) if action.reads else state
            result = action.run(state_to_use, **inputs)
            new_state = action.update(result, state)

        # Add metadata
        result = result.copy()
        result["processed_by"] = f"{self.specialization}_actor_{self.actor_id}"
        new_state = new_state.update(processed_by=f"{self.specialization}_actor_{self.actor_id}")

        # Serialize before returning
        return result, new_state.serialize()

    def get_stats(self):
        return {
            "actor_id": self.actor_id,
            "specialization": self.specialization,
            "request_count": self.request_count,
        }


# ============================================================================
# Step 2: Actor Pool Manager for Specialized Actors
# ============================================================================


class SpecializedActorPool:
    """Manages pools of specialized actors (e.g., GPU actors, DB actors)"""

    def __init__(self):
        self.pools = {}
        self.ray_initialized = False

    def _ensure_ray_initialized(self):
        if not self.ray_initialized:
            if not ray.is_initialized():
                ray.init(ignore_reinit_error=True)
            self.ray_initialized = True

    def get_actor_pool(self, specialization: str, num_actors: int = 2):
        """Get or create a pool of actors for a specialization"""
        if specialization not in self.pools:
            self._ensure_ray_initialized()
            print(f"[Pool] Creating {num_actors} actors for {specialization}...")
            actors = [SpecializedActor.remote(i, specialization) for i in range(num_actors)]
            self.pools[specialization] = {
                "actors": actors,
                "next_idx": 0,
            }
        return self.pools[specialization]

    def get_actor(self, specialization: str, num_actors: int = 2):
        """Get next available actor for a specialization (round-robin)"""
        pool = self.get_actor_pool(specialization, num_actors)
        actor = pool["actors"][pool["next_idx"]]
        pool["next_idx"] = (pool["next_idx"] + 1) % len(pool["actors"])
        return actor

    def get_all_stats(self):
        """Get statistics from all actor pools"""
        stats = {}
        for specialization, pool in self.pools.items():
            futures = [actor.get_stats.remote() for actor in pool["actors"]]
            stats[specialization] = ray.get(futures)
        return stats


# ============================================================================
# Step 3: Interceptor for Actions on Ray Worker
# ============================================================================


class WorkerLevelInterceptor(ActionExecutionInterceptorHook):
    """
    Interceptor that runs on the Ray worker where the application executes.
    Routes tagged actions to specialized Ray actors, executes others locally.
    """

    def __init__(self, actor_pool: SpecializedActorPool):
        self.actor_pool = actor_pool
        self.local_executions = []
        self.remote_executions = []

    def should_intercept(self, *, action: Action, **kwargs) -> bool:
        """Intercept actions tagged with 'gpu' or 'db' to route to specialized actors"""
        return any(tag in action.tags for tag in ["gpu", "db", "specialized"])

    def intercept_run(
        self, *, action: Action, state: State, inputs: Dict[str, Any], **kwargs
    ) -> dict:
        """Route action to specialized actor or execute locally"""
        # Determine which specialization to use based on tags
        specialization = None
        if "gpu" in action.tags:
            specialization = "gpu"
        elif "db" in action.tags:
            specialization = "db"
        elif "specialized" in action.tags:
            specialization = "specialized"

        if specialization:
            # Route to specialized actor
            self.remote_executions.append((action.name, specialization))
            actor = self.actor_pool.get_actor(specialization)

            # Serialize state before sending
            state_subset = state.subset(*action.reads) if action.reads else state
            state_dict = state_subset.serialize()

            # Execute on actor
            result_ref = actor.execute_action.remote(action, state_dict, inputs)
            result, new_state_dict = ray.get(result_ref)

            # Deserialize new state
            if hasattr(action, "single_step") and action.single_step:
                new_state = State.deserialize(new_state_dict)
                result_with_state = result.copy()
                result_with_state["__INTERCEPTOR_NEW_STATE__"] = new_state
                return result_with_state

            return result
        else:
            # Should not happen (should_intercept should prevent this)
            # But if it does, execute locally
            self.local_executions.append(action.name)
            if hasattr(action, "single_step") and action.single_step:
                result, new_state = action.run_and_update(state, **inputs)
                result_with_state = result.copy()
                result_with_state["__INTERCEPTOR_NEW_STATE__"] = new_state
                return result_with_state
            else:
                state_to_use = state.subset(*action.reads) if action.reads else state
                return action.run(state_to_use, **inputs)


# ============================================================================
# Step 4: Define Actions
# ============================================================================


@action(reads=["count"], writes=["count", "last_action"], tags=["local"])
def local_action(state: State) -> tuple:
    """Local action - runs on Ray worker (not on specialized actor)"""
    print(f"[Ray Worker - Local] Executing local_action, count={state['count']}")
    result = {
        "count": state["count"] + 1,
        "last_action": "local_action",
    }
    return result, state.update(**result)


@action(reads=["count"], writes=["count", "last_action", "processed_by"], tags=["gpu"])
def gpu_action(state: State) -> tuple:
    """
    GPU-intensive action - will be routed to GPU actor.
    THIS CODE RUNS ON THE GPU ACTOR!
    """
    print(f"[GPU Actor] Processing GPU action, count={state['count']}")
    time.sleep(0.2)  # Simulate GPU computation
    result = {
        "count": state["count"] * 2,
        "last_action": "gpu_action",
        "processed_by": "unknown",  # Actor will set this
    }
    return result, state.update(**result)


@action(reads=["count"], writes=["count", "last_action", "processed_by"], tags=["db"])
def db_action(state: State) -> tuple:
    """
    Database-intensive action - will be routed to DB actor.
    THIS CODE RUNS ON THE DB ACTOR!
    """
    print(f"[DB Actor] Processing DB action, count={state['count']}")
    time.sleep(0.1)  # Simulate database query
    result = {
        "count": state["count"] + 10,
        "last_action": "db_action",
        "processed_by": "unknown",  # Actor will set this
    }
    return result, state.update(**result)


@action(reads=["count"], writes=["count", "last_action"], tags=["local"])
def local_action_2(state: State) -> tuple:
    """Another local action - runs on Ray worker"""
    print(f"[Ray Worker - Local] Executing local_action_2, count={state['count']}")
    result = {
        "count": state["count"] - 5,
        "last_action": "local_action_2",
    }
    return result, state.update(**result)


# ============================================================================
# Step 5: Ray Remote Function to Run Burr Application with Persistence
# ============================================================================


@ray.remote
def run_burr_application_on_worker(
    initial_state: dict,
    app_id: str,
    partition_key: str,
    db_config: Optional[Dict[str, Any]],
    actor_pool_stats: dict,
    app_config: dict,
    resume: bool = False,
) -> dict:
    """
    Runs an entire Burr application on a Ray worker with PostgreSQL persistence.

    This function:
    1. Creates a PostgreSQL persister (if configured)
    2. Creates a Burr application with the provided state
    3. Uses an interceptor to route actions to specialized actors
    4. Executes the application workflow
    5. State is automatically checkpointed after each step
    6. Returns the final state and execution stats

    :param initial_state: Initial state for the application
    :param app_id: Unique identifier for this application instance
    :param partition_key: Partition key for state persistence
    :param db_config: PostgreSQL connection config (None to disable persistence)
    :param actor_pool_stats: Stats tracking (unused, for future use)
    :param app_config: Application configuration
    :param resume: Whether to resume from saved state (if available)
    """
    print("[Ray Worker] Starting Burr application execution...")
    print(f"[Ray Worker] App ID: {app_id}, Partition: {partition_key}")
    print(f"[Ray Worker] Initial state: {initial_state}")

    # Create actor pool (shared across all apps on this worker)
    actor_pool = SpecializedActorPool()

    # Create interceptor (runs on this worker)
    interceptor = WorkerLevelInterceptor(actor_pool)

    # Create PostgreSQL persister if configured
    persister = None
    if db_config and PostgreSQLPersister:
        try:
            print(
                f"[Ray Worker] Connecting to PostgreSQL at {db_config.get('host', 'localhost')}:{db_config.get('port', 5432)}"
            )
            persister = PostgreSQLPersister.from_values(
                db_name=db_config.get("db_name", "postgres"),
                user=db_config.get("user", "postgres"),
                password=db_config.get("password", "postgres"),
                host=db_config.get("host", "localhost"),
                port=db_config.get("port", 5432),
                table_name=db_config.get("table_name", "burr_state"),
            )
            # Initialize table if needed
            if not persister.is_initialized():
                persister.initialize()
                print(
                    f"[Ray Worker] Created PostgreSQL table: {db_config.get('table_name', 'burr_state')}"
                )
            else:
                print(
                    f"[Ray Worker] Using existing PostgreSQL table: {db_config.get('table_name', 'burr_state')}"
                )
        except Exception as e:
            print(f"[Ray Worker] Warning: Failed to connect to PostgreSQL: {e}")
            print("[Ray Worker] Continuing without persistence...")
            persister = None
    elif db_config and not PostgreSQLPersister:
        print(
            "[Ray Worker] Warning: PostgreSQL persister not available. Install with: pip install 'burr[postgresql]'"
        )
        persister = None

    # Build the application
    from burr.core import ApplicationBuilder

    builder = (
        ApplicationBuilder()
        .with_actions(
            local_action,
            gpu_action,
            db_action,
            local_action_2,
        )
        .with_transitions(
            ("local_action", "gpu_action"),
            ("gpu_action", "db_action"),
            ("db_action", "local_action_2"),
        )
        .with_entrypoint("local_action")
        .with_hooks(interceptor)
        .with_identifiers(app_id=app_id, partition_key=partition_key)
    )

    # Add persistence if configured
    if persister:
        builder = builder.with_state_persister(persister)

    # Initialize from saved state if resuming
    if resume and persister:
        try:
            builder = builder.initialize_from(
                persister,
                resume_at_next_action=True,
                default_state=initial_state,
                default_entrypoint="local_action",
            )
            print("[Ray Worker] Attempting to resume from saved state...")
        except Exception as e:
            print(f"[Ray Worker] Could not resume from saved state: {e}")
            print("[Ray Worker] Starting fresh...")
            builder = builder.with_state(**initial_state)
    else:
        builder = builder.with_state(**initial_state)

    app = builder.build()

    # Execute the application
    print("[Ray Worker] Executing application workflow...")
    execution_log = []
    checkpoint_count = 0

    while True:
        action, result, state = app.step()
        checkpoint_count += 1
        execution_log.append(
            {
                "action": action.name,
                "result": result,
                "state_count": state.get("count", 0),
                "sequence_id": app.sequence_id,
            }
        )
        print(
            f"[Ray Worker] Executed: {action.name}, count={state.get('count', 0)}, "
            f"sequence_id={app.sequence_id}"
        )

        # State is automatically saved by the persister after each step
        if persister:
            print(f"[Ray Worker] State checkpointed to PostgreSQL (sequence_id={app.sequence_id})")

        # Check if we've reached the end
        next_action = app.get_next_action()
        if next_action is None:
            break

    # Get final state
    final_state = app.state.get_all()

    # Get execution stats
    local_actions = [
        entry["action"]
        for entry in execution_log
        if entry["action"] not in [name for name, _ in interceptor.remote_executions]
    ]
    stats = {
        "local_executions": local_actions,
        "remote_executions": interceptor.remote_executions,
        "actor_pool_stats": actor_pool.get_all_stats(),
        "execution_log": execution_log,
        "final_state": final_state,
        "checkpoint_count": checkpoint_count,
        "app_id": app_id,
        "partition_key": partition_key,
    }

    # Cleanup persister connection
    if persister:
        try:
            persister.cleanup()
        except Exception as e:
            print(f"[Ray Worker] Warning: Error closing persister: {e}")

    print(f"[Ray Worker] Application completed. Final count: {final_state.get('count', 0)}")
    return stats


# ============================================================================
# Step 6: Main Process - Submit Applications to Ray Workers
# ============================================================================


def main():
    """Demonstrate running Burr applications on Ray workers with PostgreSQL persistence"""
    print("=" * 80)
    print("Burr Application on Ray Worker with PostgreSQL Persistence")
    print("=" * 80)
    print()

    # Initialize Ray
    if not ray.is_initialized():
        ray.init(ignore_reinit_error=True)

    # PostgreSQL configuration
    # Set these via environment variables or modify here
    db_config = {
        "db_name": os.getenv("POSTGRES_DB", "postgres"),
        "user": os.getenv("POSTGRES_USER", "postgres"),
        "password": os.getenv("POSTGRES_PASSWORD", "postgres"),
        "host": os.getenv("POSTGRES_HOST", "localhost"),
        "port": int(os.getenv("POSTGRES_PORT", "5432")),
        "table_name": os.getenv("POSTGRES_TABLE", "burr_state"),
    }

    # Check if we should use persistence
    use_persistence = os.getenv("USE_PERSISTENCE", "true").lower() == "true"

    if use_persistence and not PostgreSQLPersister:
        print("Warning: PostgreSQL persister not available.")
        print("Install with: pip install 'burr[postgresql]'")
        print("Continuing without persistence...")
        use_persistence = False

    print("Main Process: Submitting applications to Ray workers...")
    if use_persistence:
        print(f"PostgreSQL: {db_config['host']}:{db_config['port']}/{db_config['db_name']}")
    else:
        print("Persistence: Disabled")
    print()

    # Submit multiple applications to run on Ray workers
    applications = []
    for i in range(3):
        app_id = f"app_{i}_{int(time.time())}"
        partition_key = "demo_partition"
        app_config = {
            "app_id": app_id,
            "workflow": "default",
        }
        initial_state = {"count": i * 10}

        # Submit to Ray worker
        future = run_burr_application_on_worker.remote(
            initial_state=initial_state,
            app_id=app_id,
            partition_key=partition_key,
            db_config=db_config if use_persistence else None,
            actor_pool_stats={},
            app_config=app_config,
            resume=False,  # Set to True to resume from saved state
        )
        applications.append((app_id, future))

    # Wait for all applications to complete
    print("\nMain Process: Waiting for applications to complete...")
    results = []
    for app_id, future in applications:
        result = ray.get(future)
        results.append((app_id, result))
        print(f"\n✅ {app_id} completed")

    # Display results
    print("\n" + "=" * 80)
    print("Execution Results")
    print("=" * 80)

    for app_id, result in results:
        print(f"\n{app_id}:")
        print(f"  Final count: {result['final_state']['count']}")
        print(f"  Checkpoints: {result['checkpoint_count']}")
        print(f"  Local executions: {result['local_executions']}")
        print(f"  Remote executions: {result['remote_executions']}")
        print("  Execution log:")
        for entry in result["execution_log"]:
            print(
                f"    - {entry['action']}: count={entry['state_count']}, "
                f"seq_id={entry['sequence_id']}"
            )

    # Display actor pool statistics
    print("\n" + "=" * 80)
    print("Actor Pool Statistics")
    print("=" * 80)

    if results:
        last_result = results[-1][1]
        for specialization, actor_stats in last_result["actor_pool_stats"].items():
            print(f"\n{specialization.upper()} Actors:")
            for stat in actor_stats:
                print(
                    f"  Actor {stat['actor_id']}: {stat['request_count']} requests "
                    f"(specialization: {stat['specialization']})"
                )

    print("\n" + "=" * 80)
    print("Key Observations")
    print("=" * 80)
    print("✅ Entire Burr applications run on Ray workers")
    print("✅ Actions tagged with 'gpu'/'db' route to specialized actors")
    print("✅ Local actions execute on the Ray worker (no actor overhead)")
    if use_persistence:
        print("✅ State automatically checkpointed to PostgreSQL after each step")
        print("✅ Can resume from saved state using initialize_from()")
    else:
        print("⚠️  Persistence disabled (set USE_PERSISTENCE=true and configure PostgreSQL)")
    print("✅ Multiple applications can share the same actor pools")
    print("✅ State properly serialized/deserialized across boundaries")

    # Cleanup
    ray.shutdown()


if __name__ == "__main__":
    main()
