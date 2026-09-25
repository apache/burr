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

# @apache-burr/core

Core TypeScript library for Apache Burr - build state machines with simple functions.

## Status

🚧 **Active Development** - Core APIs implemented, execution engine coming soon.

### Implemented
- ✅ State management with immutability & event sourcing
- ✅ Actions (two-step: run + update)
- ✅ Graph builder with type-safe transitions
- ✅ Application builder with hybrid typing & state validation
- ✅ Compile-time type safety with Zod
- ✅ Graph-state compatibility validation at compile-time

### Not Yet Implemented
- ⏳ Execution engine (run, step, stream)
- ⏳ Persistence
- ⏳ Lifecycle hooks
- ⏳ Telemetry & tracking
- ⏳ Streaming actions

## Installation

```bash
npm install @apache-burr/core zod
```

## Quick Start

```typescript
import { z } from 'zod';
import { action, GraphBuilder, ApplicationBuilder, createState, createStateWithDefaults } from '@apache-burr/core';

// 1. Define actions
const increment = action({
  reads: z.object({ count: z.number() }),
  writes: z.object({ count: z.number() }),
  update: ({ state }) => state.update({ count: state.count + 1 })
});

const reset = action({
  reads: z.object({ count: z.number() }),
  writes: z.object({ count: z.number() }),
  update: () => createState(
    z.object({ count: z.number() }),
    { count: 0 }
  )
});

// 2. Build graph
const graph = new GraphBuilder()
  .withActions({ increment, reset })
  .withTransitions(
    ['increment', 'increment', (state) => state.count < 10],
    ['increment', 'reset', (state) => state.count >= 10]
  )
  .build();

// 3. Build application (safe mode - explicit data)
const app = new ApplicationBuilder()
  .withGraph(graph)
  .withEntrypoint('increment')
  .withState(createState(
    z.object({ count: z.number() }),
    { count: 0 }
  ))
  .build();

// 3b. Or use power-user mode with Zod defaults
const appWithDefaults = new ApplicationBuilder()
  .withGraph(graph)
  .withEntrypoint('increment')
  .withState(createStateWithDefaults(
    z.object({ count: z.number().default(0) })
    // No data param needed! Zod fills defaults at runtime
  ))
  .build();

// ❌ This would fail at compile-time:
// .withState(createState(z.object({ wrong: z.string() }), { wrong: 'oops' }))
// Error: State is missing required fields from graph

// 4. Run (coming soon)
// const result = await app.run();
```

## Feature Parity with Python

### State APIs

| Feature | Python | TypeScript | Status | Notes |
|---------|--------|------------|--------|-------|
| **Immutable state** | ✅ | ✅ | **Complete** | Copy-on-write with structural sharing |
| **createState()** | ✅ | ✅ | **Complete** | Safe mode - explicit data required |
| **createStateWithDefaults()** | ❌ | ✅ | **TS-only** | Power mode - Zod defaults optional data |
| **State.update()** | ✅ | ✅ | **Complete** | Type-safe, dynamic schema extension |
| **State.get()** | ✅ | ✅ | **Complete** | Plus direct property access via Proxy |
| **State.has()** | ✅ | ✅ | **Complete** | Runtime key existence check |
| **State.subset()** | ✅ | ❌ | Not implemented | May not be needed with TS typing |
| **State.merge()** | ✅ | ❌ | Not implemented | |
| **State.wipe()** | ✅ | ❌ | Not implemented | |
| **State.increment()** | ✅ | ✅ | **Complete** | Multi-field support with object params |
| **State.append()** | ✅ | ✅ | **Complete** | Multi-field support with object params |
| **State.extend()** | ✅ | ✅ | **Complete** | Multi-field support with object params |
| **Operations/StateDelta** | ✅ | ✅ | **Complete** | Schema-aware, type-parameterized |
| **Custom serialization** | ✅ | ❌ | Not implemented | JSON-only for now |
| **History tracking** | ✅ | ❌ | Intentionally omitted | Event sourcing at app level instead |
| **Read/write restrictions** | ❌ | ✅ | **TS-only** | Compile-time + runtime enforcement |
| **Zod schema validation** | ❌ (Pydantic) | ✅ | **Complete** | Zod is required, not optional |

### Action APIs

| Feature | Python | TypeScript | Status | Notes |
|---------|--------|------------|--------|-------|
| **Two-step actions** | ✅ (`@action`) | ✅ (`action`) | **Complete** | run + update separation |
| **Reads/writes metadata** | ✅ | ✅ | **Complete** | Via Zod schemas |
| **Input validation** | ✅ | ✅ | **Complete** | Via Zod schemas |
| **Result schema** | ✅ | ✅ | **Complete** | Via Zod, object or void |
| **Streaming actions** | ✅ (`@streaming_action`) | ❌ | Not implemented | Coming soon |
| **Reducers** | ✅ | ❌ | Not implemented | May not be needed |
| **Single function** | ✅ | ❌ | Not implemented | Only two-step for now |
| **Decorators** | ✅ | ❌ | **TS uses factories** | `action` instead of `@action` |
| **Type inference** | ❌ | ✅ | **TS-only** | Full compile-time type safety |
| **Optional run()** | ❌ | ✅ | **TS enhancement** | Defaults to empty result |
| **Options object params** | ❌ | ✅ | **TS enhancement** | `{ state, inputs }` pattern |

### Graph APIs

| Feature | Python | TypeScript | Status | Notes |
|---------|--------|------------|--------|-------|
| **Graph builder** | ✅ | ✅ | **Complete** | Immutable builder pattern |
| **Add actions** | ✅ (`with_actions`) | ✅ (`withActions`) | **Complete** | Type-safe action names |
| **Add transitions** | ✅ (`with_transitions`) | ✅ (`withTransitions`) | **Complete** | Type-safe conditions |
| **Conditional transitions** | ✅ | ✅ | **Complete** | State-aware predicates |
| **Terminal transitions** | ✅ (null) | ✅ (null) | **Complete** | `to: null` for terminal |
| **Subgraphs** | ✅ | ❌ | Not implemented | |
| **Parallel execution** | ✅ | ❌ | Not implemented | |
| **Bottom-up typing** | ❌ | ✅ | **TS-only** | Infer state from actions |
| **Top-down typing** | ❌ | ✅ | **TS-only** | Enforce global state schema |
| **Generic Graph<T>** | ❌ | ✅ | **TS-only** | Compile-time state typing |

### Application APIs

| Feature | Python | TypeScript | Status | Notes |
|---------|--------|------------|--------|-------|
| **Application builder** | ✅ | ✅ | **Complete** | Immutable builder pattern |
| **with_graph** | ✅ | ✅ (`withGraph`) | **Complete** | Primary API |
| **with_actions** | ✅ | ❌ | **TS different** | Must use GraphBuilder first |
| **with_transitions** | ✅ | ❌ | **TS different** | Must use GraphBuilder first |
| **with_entrypoint** | ✅ | ✅ (`withEntrypoint`) | **Complete** | Action name validation |
| **with_state** | ✅ | ✅ (`withState`) | **Complete** | Initial state + validation |
| **State validation** | ❌ | ✅ | **TS-only** | Compile-time graph compatibility |
| **with_identifiers** | ✅ | ❌ | Not implemented | app_id, partition_key |
| **with_tracker** | ✅ | ❌ | Not implemented | Telemetry |
| **with_hooks** | ✅ | ❌ | Not implemented | Lifecycle hooks |
| **initialize_from** | ✅ | ❌ | Not implemented | Load from persister |
| **run()** | ✅ | ❌ | Not implemented | Execute to completion |
| **step()** | ✅ | ❌ | Not implemented | Single step execution |
| **stream_result()** | ✅ | ❌ | Not implemented | Async iteration |
| **iterate()** | ✅ | ❌ | Not implemented | Generator pattern |
| **Generic Application<T>** | ❌ | ✅ | **TS-only** | Compile-time state typing |
| **Hybrid type inference** | ❌ | ✅ | **TS-only** | Infer from graph or state |
| **Both build orders** | ❌ | ✅ | **TS-only** | State→Graph or Graph→State |

### Persistence APIs

| Feature | Python | TypeScript | Status | Notes |
|---------|--------|------------|--------|-------|
| **Base persister** | ✅ | ❌ | Not implemented | |
| **SQLite persister** | ✅ | ❌ | Not implemented | |
| **PostgreSQL persister** | ✅ | ❌ | Not implemented | |
| **In-memory persister** | ✅ | ❌ | Not implemented | |
| **Custom persisters** | ✅ | ❌ | Not implemented | |

### Tracking/Telemetry APIs

| Feature | Python | TypeScript | Status | Notes |
|---------|--------|------------|--------|-------|
| **Local tracker** | ✅ | ❌ | Not implemented | |
| **OpenTelemetry** | ✅ | ❌ | Not implemented | |
| **Custom trackers** | ✅ | ❌ | Not implemented | |
| **Lifecycle hooks** | ✅ | ❌ | Not implemented | |

### Serialization APIs

| Feature | Python | TypeScript | Status | Notes |
|---------|--------|------------|--------|-------|
| **JSON serialization** | ✅ | ✅ | **Partial** | Basic support, no custom |
| **Custom serializers** | ✅ | ❌ | Not implemented | |
| **Pickle support** | ✅ | N/A | Not applicable | JS doesn't have pickle |

## TypeScript-Specific Features

### Unique to TypeScript (Not in Python)

1. **Compile-time Type Safety**
   - Full type inference from Zod schemas
   - Catch errors at build time, not runtime
   - IDE autocomplete for state fields

2. **Read/Write Restrictions**
   - Actions can only read from `reads` schema
   - Actions can only write to `writes` schema
   - Enforced at both compile-time and runtime

3. **Dynamic Schema Extension**
   - `state.update({ newField: value })` extends the schema
   - Type system tracks new fields automatically
   - Runtime Zod schema stays compatible

4. **Immutable Builder Pattern**
   - GraphBuilder and ApplicationBuilder are immutable
   - Each method returns a new instance
   - Type information preserved through chaining

5. **Proxy-based State Access**
   - Direct property access: `state.count` instead of `state.get('count')`
   - Still maintains immutability guarantees
   - Validates against schema at runtime

6. **Generic Type Parameters**
   - `Graph<TStateSchema>`, `Application<TStateSchema>`
   - Type-level state tracking
   - Enables compile-time compatibility checks

7. **Hybrid Typing Modes**
   - Bottom-up: Infer state from actions
   - Top-down: Enforce global state schema
   - Same API supports both patterns

8. **Graph-State Compatibility Validation**
   - ApplicationBuilder validates state matches graph requirements
   - Works in both orders: `withState()` → `withGraph()` or `withGraph()` → `withState()`
   - Descriptive compile-time errors show exactly what's missing
   - State must be a superset of graph requirements (can have extra fields)

9. **Dual State Creation Modes**
   - **Safe mode** (`createState`): Explicit data required at compile-time
   - **Power mode** (`createStateWithDefaults`): Optional data, Zod defaults fill at runtime
   - Opt-in convenience without sacrificing safety by default
   ```typescript
   // Safe: compile error if data missing
   createState(schema, { count: 0 })
   
   // Power: no data needed if schema has defaults
   createStateWithDefaults(z.object({ count: z.number().default(0) }))
   ```

## Design Principles

### TypeScript Port Goals

1. **Type Safety First**: Leverage TypeScript's type system for compile-time guarantees
2. **Zod Integration**: Use Zod throughout for runtime validation and type inference
3. **Immutability**: Immutable data structures with structural sharing
4. **Event Sourcing**: Operations are first-class, serializable objects
5. **Async-Only**: All actions are async (no sync operations)
6. **Clean API**: No decorators (use factory functions instead)

### Key Differences from Python

| Aspect | Python | TypeScript | Rationale |
|--------|--------|------------|-----------|
| **Schema library** | Pydantic (optional) | Zod (required) | Type erasure requires runtime metadata |
| **Type safety** | Runtime + mypy | Compile-time + runtime | TypeScript's type system is more powerful |
| **State validation** | Runtime only | Compile-time | Graph-state compatibility checked at build time |
| **Decorators** | `@action` | `action()` | Factory pattern is more idiomatic in TS |
| **Builder pattern** | Mutable | Immutable | Preserves type information through chaining |
| **State access** | `state.get()` | `state.field` + `state.get()` | Proxy enables both patterns |
| **Execution** | Sync + async | Async only | Modern JS is async-first |

## Contributing

This is an active port of Python Burr to TypeScript. We're focusing on:

1. ✅ Core APIs (state, actions, graph, application)
2. ⏳ Execution engine
3. ⏳ Persistence layer
4. ⏳ Telemetry & tracking
5. ⏳ Streaming actions

## Documentation

See the [implementation summary](./APPLICATION_IMPLEMENTATION_SUMMARY.md) for detailed architecture notes.

## License

Apache License 2.0

