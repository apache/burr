<!--
Licensed to the Apache Software Foundation (ASF) under one
or more contributor license agreements.  See the NOTICE file
distributed with this work for additional information
regarding copyright ownership.  The ASF licenses this file
to you under the Apache License, Version 2.0 (the
"License"); you may not use this file except in compliance
with the License.  You may obtain a copy of the License at

  http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing,
software distributed under the License is distributed on an
"AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
KIND, either express or implied.  See the License for the
specific language governing permissions and limitations
under the License.
-->

# Apache Burr (TypeScript)

TypeScript implementation of Apache Burr - a framework for building applications that make decisions (chatbots, agents, simulations, etc.) from simple building blocks.

## Status

🚧 **Work in Progress** - This is an active port of the Python implementation. APIs may change.

## Structure

- `packages/burr-core/` - Core library (state machine, actions, application)
- `examples/` - TypeScript examples
- `tests/` - Integration tests

## Getting Started

```bash
# Install dependencies
npm install

# Build all packages
npm run build

# Run tests
npm test
```

## Documentation

See the main [Burr documentation](https://burr.apache.org/) for concepts and guides. TypeScript-specific documentation coming soon.

## Compatibility

This implementation aims to match the Python version's core functionality with TypeScript idioms and best practices.

## Feature Parity

### State API

| Feature | Python | TypeScript | Notes |
|---------|--------|------------|-------|
| `State()` constructor | ✅ | ✅ | |
| `state.get(key)` | ✅ | ✅ | TS throws on missing key; Python returns None |
| `state.get(key, default)` | ✅ | ❌ | Python supports default values |
| `state["key"]` access | ✅ | ❌ | Python dict syntax; TS uses `get()` |
| `state.has(key)` / `key in state` | ✅ | ✅ | |
| `state.keys()` | ✅ | ✅ | |
| `state.getAll()` | ✅ | ✅ | |
| `state.update(**kwargs)` | ✅ | ✅ | Python uses kwargs; TS uses object |
| `state.append(key=val)` | ✅ | ✅ | Python: multiple keys; TS: single key |
| `state.extend(key=vals)` | ✅ | ✅ | Python: multiple keys; TS: single key |
| `state.increment(key=delta)` | ✅ | ✅ | Python: multiple keys; TS: single key |
| `state.subset(*keys)` | ✅ | ✅ | TS version is strict (throws on missing keys) |
| `state.merge(other)` | ✅ | ✅ | |
| `state.wipe(delete/keep)` | ✅ | ❌ | Delete operations not yet implemented |
| `state.serialize()` | ✅ | ✅ | Basic JSON serialization |
| `state.deserialize()` | ✅ | ✅ | Basic JSON deserialization |
| Custom field serialization | ✅ | ❌ | `register_field_serde()` not implemented |
| Typing system | ✅ | ❌ | Python has pluggable typing; TS uses generics |
| Type safety | ❌ | ✅ | TS has compile-time type checking |

### Actions

| Feature | Python | TypeScript | Notes |
|---------|--------|------------|-------|
| `@action` decorator | ✅ | ❌ | TS uses `action()` function instead |
| `Action` class | ✅ | ✅ | |
| `action()` helper function | ✅ | ✅ | Primary way to create actions in TS |
| `reads` / `writes` specification | ✅ | ✅ | Uses Zod schemas in TS |
| `inputs` specification | ✅ | ✅ | Uses Zod schemas in TS |
| Sync actions | ✅ | ❌ | TS is async-only |
| Async actions | ✅ | ✅ | All TS actions are async |
| Streaming actions | ✅ | ✅ | `StreamingAction` with `streamRun()` returning `AsyncGenerator` |
| Action validation (inputs/reads/writes) | ✅ | ✅ | Runtime validation with Zod |
| `result` type specification | ✅ | ✅ | Uses Zod schemas in TS |
| Separate run/update phases | ✅ | ✅ | |
| Single-step actions | ✅ | ✅ | Omit `result`/`run` to create update-only actions |

### Application

| Feature | Python | TypeScript | Notes |
|---------|--------|------------|-------|
| `ApplicationBuilder` | ✅ | ✅ | |
| `Application.step()` | ✅ | ✅ | Async only in TS |
| `Application.run()` | ✅ | ✅ | Async only in TS |
| `Application.iterate()` | ✅ | ✅ | Async generator in TS |
| `Application.astep()` | ✅ | ❌ | TS step() is always async |
| `Application.arun()` | ✅ | ❌ | TS run() is always async |
| `Application.aiterate()` | ✅ | ❌ | TS iterate() is always async |
| Initial state | ✅ | ✅ | |
| Entrypoint specification | ✅ | ✅ | |
| Halt conditions (before/after) | ✅ | ✅ | `haltBefore` / `haltAfter` |
| Application state access | ✅ | ✅ | `app.state` property |
| Initial state access | ❌ | ❌ | Removed for Python parity |
| Application ID | ✅ | ✅ | `uid` in Python, `appId` in TS |
| Partition key | ✅ | ✅ | |
| Sequence ID access | ✅ | ✅ | Stored in `state.executionMetadata.sequenceId` |
| Fork→Launch→Gather→Commit pattern | ❌ | ✅ | TS uses 4-phase execution with defense-in-depth validation |
| Framework metadata in state | ✅ | ✅ | TS: `appMetadata`/`executionMetadata`, Python: `__*` fields |
| Application context | ✅ | ✅ | `ApplicationContext` interface for sub-graph execution |
| `has_next_action()` | ✅ | ❌ | Not yet implemented |
| `get_next_action()` | ✅ | ❌ | Internal in TS |
| `update_state()` | ✅ | ❌ | Not yet implemented |
| `reset_to_entrypoint()` | ✅ | ❌ | Not yet implemented |
| Streaming actions | ✅ | ✅ | `streamStep()` method with `StreamingResultContainer` |
| `visualize()` | ✅ | ❌ | Not yet implemented |
| Parent/spawning pointers | ✅ | 🚧 | Hook interfaces defined; not wired into builder/application |

### Graph

| Feature | Python | TypeScript | Notes |
|---------|--------|------------|-------|
| `Graph` class | ✅ | ✅ | |
| `GraphBuilder` | ✅ | ✅ | |
| Transitions (unconditional) | ✅ | ✅ | |
| Conditional transitions | ✅ | ✅ | Function-based conditions |
| Default/fallback transitions | ✅ | ✅ | |
| Action tags | ✅ | ❌ | Not yet implemented |
| Graph validation | ✅ | ❌ | Not yet implemented |
| Cycle detection | ✅ | ❌ | Not yet implemented |
| Graph visualization | ✅ | ❌ | Not yet implemented |
| `getTransitionsFrom()` | ✅ | ✅ | |
| `getAction()` | ✅ | ✅ | |
| `hasAction()` | ✅ | ✅ | |

### Persistence

| Feature | Python | TypeScript | Notes |
|---------|--------|------------|-------|
| `Persister` interface | ✅ | ✅ | `StateLoader`, `StateSaver`, `StatePersister` interfaces |
| In-memory persister | ✅ | ✅ | `InMemoryPersister` for testing |
| `PersisterHook` (lifecycle integration) | ✅ | ✅ | Wraps `StateSaver` as `PostRunStepHook` |
| State serialization for persistence | ✅ | ✅ | Via `serde.ts` with tagged-value convention |
| Builder integration | ✅ | ✅ | `withStatePersister()` / `withStateLoader()` on `ApplicationBuilder` |
| State resumption from persistence | ✅ | ✅ | `ApplicationBuilder.build()` loads state from persister if available |
| File-based persister | ✅ | ❌ | Not yet implemented |
| SQLite persister | ✅ | ❌ | Not yet implemented |
| PostgreSQL persister | ✅ | ❌ | Not yet implemented |
| Redis persister | ✅ | ❌ | Not yet implemented |
| MongoDB persister | ✅ | ❌ | Not yet implemented |
| Custom persisters | ✅ | ✅ | Implement `StatePersister` interface |
| State snapshots | ✅ | ❌ | Not yet implemented |
| State history | ✅ | ❌ | Not yet implemented |

### Lifecycle & Hooks

| Feature | Python | TypeScript | Notes |
|---------|--------|------------|-------|
| Lifecycle hooks interface | ✅ | ✅ | `LifecycleAdapter` union type with 11 hook interfaces |
| `PreRunStepHook` | ✅ | ✅ | Fires before each action execution |
| `PostRunStepHook` | ✅ | ✅ | Fires after each action (including on failure) |
| `PostApplicationCreateHook` | ✅ | ✅ | Fires after `ApplicationBuilder.build()` |
| `PreExecuteCallHook` / `PostExecuteCallHook` | ✅ | ✅ | Wraps step/run/iterate/streamStep calls |
| `PreStartStreamHook` / `PostStreamItemHook` / `PostEndStreamHook` | ✅ | ✅ | Stream lifecycle hooks |
| `PreStartSpanHook` / `PostEndSpanHook` / `DoLogAttributeHook` | ✅ | ✅ | Tracing span hooks |
| `LifecycleAdapterSet` dispatcher | ✅ | ✅ | Duck-typed dispatch, collects errors via `AggregateError` |
| Multiple hooks composition | ✅ | ✅ | `withHooks()` accepts multiple adapters |
| Async-only hooks | ❌ | ✅ | Python has sync + async; TS is async-only |

### Tracking & Observability

| Feature | Python | TypeScript | Notes |
|---------|--------|------------|-------|
| Tracing/spans | ✅ | ✅ | `ActionSpan`, `ActionSpanTracer`, nested span support |
| `TracerFactory` | ✅ | ✅ | Creates tracers per action execution |
| `AsyncLocalStorage` context | ❌ | ✅ | `runWithTracer()`, `getCurrentTracer()`, `trace()` auto-span |
| Span lifecycle hooks | ✅ | ✅ | `PreStartSpanHook`, `PostEndSpanHook`, `DoLogAttributeHook` |
| Tracking client | ✅ | ❌ | Not yet implemented |
| Local tracking | ✅ | ❌ | Not yet implemented |
| Remote tracking | ✅ | ❌ | Not yet implemented |
| S3 tracking | ✅ | ❌ | Not yet implemented |
| OpenTelemetry integration | ✅ | ❌ | Not yet implemented |

### Parallelism & Sub-graphs

| Feature | Python | TypeScript | Notes |
|---------|--------|------------|-------|
| `RunnableGraph` | ✅ | ✅ | Graph + entrypoint + halt conditions |
| `SubGraphTask` | ✅ | ✅ | Runs sub-graph with cascaded persistence/lifecycle |
| `TaskBasedParallelAction` | ✅ | ✅ | Abstract base: implement `tasks()` + `reduce()` |
| `MapActionsAndStates` | ✅ | ✅ | Cartesian product of actions x states |
| `MapActions` | ✅ | ✅ | Multiple actions over same state |
| `MapStates` | ✅ | ✅ | One action over multiple state variants |
| `Promise.all()` execution | ❌ | ✅ | Python uses thread/process pools; TS uses async concurrency |
| Cascade behavior | ✅ | ✅ | `'cascade'` / `null` / explicit for persistence, lifecycle |
| `ApplicationContext` | ✅ | ✅ | Carries identity + persistence refs to sub-graphs |

### Serialization

| Feature | Python | TypeScript | Notes |
|---------|--------|------------|-------|
| Basic JSON serialization | ✅ | ✅ | `serializeState()` / `deserializeState()` |
| Tagged-value convention | ✅ | ✅ | `{ __serde_type: "Date", value: "..." }` for non-JSON types |
| Built-in type support | ✅ | ✅ | Date, Map, Set, RegExp, BigInt |
| Custom serializers/deserializers | ✅ | ✅ | Via `SerdeOptions` with custom Maps |
| Per-field serialization (`register_field_serde`) | ✅ | ❌ | Python-specific; TS uses per-type custom serde |

### Integrations

| Feature | Python | TypeScript | Notes |
|---------|--------|------------|-------|
| Hamilton integration | ✅ | ❌ | Not yet implemented |
| LangChain integration | ✅ | ❌ | Not yet implemented |
| Haystack integration | ✅ | ❌ | Not yet implemented |
| Pydantic integration | ✅ | ❌ | Not yet implemented |
| Streamlit integration | ✅ | ❌ | Not yet implemented |
| Ray integration | ✅ | ❌ | Not yet implemented |
| Custom integrations | ✅ | ❌ | Not yet implemented |

### Core Abstractions

| Feature | Python | TypeScript | Notes |
|---------|--------|------------|-------|
| Operation/StateDelta pattern | ✅ | ✅ | Implemented for state mutations |
| Immutable state | ✅ | ✅ | |
| Copy-on-write optimization | ✅ | ✅ | Uses `structuredClone` |
| Generic type support | ❌ | ✅ | TypeScript generics provide type safety |
| Serializable operations | ✅ | ✅ | Operations can be serialized to JSON |
| Async-first design | ❌ | ✅ | All TS actions/execution is async |
| Schema validation (Zod) | ❌ | ✅ | TS uses Zod for runtime validation |
| Framework metadata in state | ✅ | ✅ | `appMetadata` / `executionMetadata` |

### Legend
- ✅ **Implemented** - Feature is available and tested
- 🚧 **Partial** - Feature is partially implemented or in progress
- ❌ **Not Implemented** - Feature not yet available

### Implementation Priority

**Phase 1 (✅ COMPLETED):**
- ✅ State API core operations
- ✅ State immutability & operations (update, append, extend, increment, subset)
- ✅ Strict subset validation (throws on missing keys)
- ✅ Basic serialization
- ✅ Actions with Zod validation
- ✅ Application & ApplicationBuilder
- ✅ Graph & transitions
- ✅ Execution engine (step/run/iterate)
- ✅ Fork→Launch→Gather→Commit execution pattern
- ✅ Defense-in-depth validation
- ✅ Framework metadata (appMetadata/executionMetadata)
- ✅ Halt conditions (haltBefore/haltAfter)
- ✅ Error propagation with context

**Phase 2 (✅ COMPLETED):**
- ✅ Streaming actions (`StreamingAction`, `StreamingResultContainer`, `streamStep()`)
- ✅ Lifecycle hooks (11 hook types, `LifecycleAdapterSet` dispatcher)
- ✅ Application context (`ApplicationContext` for sub-graph execution)
- ✅ Persistence interfaces (`StateLoader`, `StateSaver`, `InMemoryPersister`, `PersisterHook`)
- ✅ Serialization (`serde.ts` with tagged-value convention for Date, Map, Set, RegExp, BigInt)
- ✅ Tracing & spans (`ActionSpan`, `ActionSpanTracer`, `TracerFactory`, `AsyncLocalStorage` context)
- ✅ Parallelism & sub-graphs (`RunnableGraph`, `SubGraphTask`, `MapActions`, `MapStates`, `MapActionsAndStates`)

**Phase 3 (Current - Developer Experience):**
- Action tags
- Helper methods (reset_to_entrypoint, has_next_action, etc.)
- Graph validation & cycle detection
- Graph visualization
- Better error messages
- Parent/spawning pointer wiring (hook interfaces exist)

**Phase 4 (Long Term - Production Features):**
- Concrete persistence adapters (SQLite, PostgreSQL, Redis, MongoDB, file-based)
- Tracking clients (local, remote, S3)
- OpenTelemetry integration
- Integrations (LangChain, etc.)

<!-- TODO: Set up npm publishing workflow for @apache-burr/core (see .github/workflows/release-validation.yml for the Python pattern) -->

