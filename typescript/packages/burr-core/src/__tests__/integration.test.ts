// Licensed to the Apache Software Foundation (ASF) under one
// or more contributor license agreements.  See the NOTICE file
// distributed with this work for additional information
// regarding copyright ownership.  The ASF licenses this file
// to you under the Apache License, Version 2.0 (the
// "License"); you may not use this file except in compliance
// with the License.  You may obtain a copy of the License at
//
//   http://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing,
// software distributed under the License is distributed on an
// "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
// KIND, either express or implied.  See the License for the
// specific language governing permissions and limitations
// under the License.

/**
 * Integration tests mirroring Python's tests/integration_tests/test_app.py
 *
 * These prove the full stack works end-to-end:
 *   builder → graph → actions → execution → serde → persistence → resumption
 *
 * The core scenario: step through a multi-action pipeline one step at a time,
 * rebuilding the entire application from persistence between each step, and
 * verify everything survives the serialize → persist → load → deserialize
 * round-trip.
 */

import { z } from 'zod';
import { action, createState, GraphBuilder, ApplicationBuilder } from '../index';
import { InMemoryPersister } from '../persistence';

// ============================================================================
// Actions — mirrors Python's basic_action → pydantic_action → ... pipeline
// ============================================================================

const basicAction = action({
  reads: z.object({}),
  writes: z.object({ dict: z.record(z.string(), z.unknown()) }),
  inputs: z.object({ userInput: z.string() }),
  result: z.object({ dict: z.record(z.string(), z.unknown()) }),
  run: async ({ inputs }) => {
    const v = {
      foo: 1,
      bar: '2',
      bool: true,
      none: null,
      input: inputs.userInput,
    };
    return { dict: v };
  },
  update: ({ result, state }) => state.update({ dict: result.dict }),
});

const transformAction = action({
  reads: z.object({ dict: z.record(z.string(), z.unknown()) }),
  writes: z.object({ transformed: z.object({ f1: z.number(), f2: z.boolean() }) }),
  result: z.object({ transformed: z.object({ f1: z.number(), f2: z.boolean() }) }),
  run: async ({ state }) => ({
    transformed: {
      f1: state.dict.foo as number,
      f2: state.dict.bool as boolean,
    },
  }),
  update: ({ result, state }) => state.update({ transformed: result.transformed }),
});

const formatAction = action({
  reads: z.object({ transformed: z.object({ f1: z.number(), f2: z.boolean() }) }),
  writes: z.object({ doc: z.string() }),
  result: z.object({ doc: z.string() }),
  run: async ({ state }) => ({
    doc: `foo: ${state.transformed.f1}, bar: ${state.transformed.f2}`,
  }),
  update: ({ result, state }) => state.update({ doc: result.doc }),
});

const terminalAction = action({
  reads: z.object({ doc: z.string() }),
  writes: z.object({}),
  result: z.object({ output: z.string() }),
  run: async ({ state }) => ({ output: state.doc }),
  // @ts-expect-error — empty writes is valid for read-only terminal actions
  update: ({ state }) => state,
});

// ============================================================================
// Helpers
// ============================================================================

function buildGraph() {
  return new GraphBuilder()
    .withActions({ basicAction, transformAction, formatAction, terminalAction })
    .withTransitions(
      ['basicAction', 'terminalAction', (s: any) => s.dict?.foo === 0],
      ['basicAction', 'transformAction'],
      ['transformAction', 'formatAction'],
      ['formatAction', 'terminalAction'],
      ['terminalAction', null],
    )
    .build();
}

const StateSchema = z.object({
  dict: z.record(z.string(), z.unknown()).optional(),
  transformed: z.object({ f1: z.number(), f2: z.boolean() }).optional(),
  doc: z.string().optional(),
});

async function buildApplication(
  persister: InMemoryPersister,
  partitionKey: string,
  appId: string,
) {
  const graph = buildGraph();
  const defaultState = createState(StateSchema, {});

  const builder = await new ApplicationBuilder()
    .withGraph(graph)
    .withStatePersister(persister)
    .initializeFrom({
      loader: persister,
      partitionKey,
      appId,
      defaultState,
      defaultEntrypoint: 'basicAction',
      resumeAtNextAction: true,
    });

  return builder.build();
}

// ============================================================================
// Tests
// ============================================================================

describe('Integration: full pipeline with persistence round-trip', () => {
  test('step-by-step with rebuild from persistence between each step', async () => {
    const persister = new InMemoryPersister();
    await persister.initialize();
    const appId = 'integration-test';
    const partitionKey = 'test-pk';

    // --- Step 1: basicAction ---
    let app = await buildApplication(persister, partitionKey, appId);
    const step1 = await app.step({ inputs: { userInput: 'hello' } });
    expect(step1).not.toBeNull();
    expect(step1!.action.name).toBe('basicAction');
    const state1 = step1!.state.data;
    expect(state1.dict).toEqual({
      foo: 1, bar: '2', bool: true, none: null, input: 'hello',
    });

    // --- Step 2: transformAction (rebuilt from persistence) ---
    app = await buildApplication(persister, partitionKey, appId);
    const step2 = await app.step();
    expect(step2).not.toBeNull();
    expect(step2!.action.name).toBe('transformAction');
    const state2 = step2!.state.data;
    expect(state2.transformed).toEqual({ f1: 1, f2: true });
    // dict should still be present from step 1
    expect(state2.dict).toEqual(state1.dict);

    // --- Step 3: formatAction (rebuilt from persistence) ---
    app = await buildApplication(persister, partitionKey, appId);
    const step3 = await app.step();
    expect(step3).not.toBeNull();
    expect(step3!.action.name).toBe('formatAction');
    const state3 = step3!.state.data;
    expect(state3.doc).toBe('foo: 1, bar: true');
    // previous fields survive
    expect(state3.dict).toEqual(state1.dict);
    expect(state3.transformed).toEqual(state2.transformed);

    // --- Step 4: terminalAction (rebuilt from persistence) ---
    app = await buildApplication(persister, partitionKey, appId);
    const step4 = await app.step();
    expect(step4).not.toBeNull();
    expect(step4!.action.name).toBe('terminalAction');
    expect(step4!.result).toEqual({ output: 'foo: 1, bar: true' });

    // State accumulates across all steps
    const state4 = step4!.state.data;
    expect(state4.dict).toEqual(state1.dict);
    expect(state4.transformed).toEqual(state2.transformed);
    expect(state4.doc).toBe(state3.doc);

    // Persister has a record for every step
    expect(persister.records.length).toBe(4);
    expect(persister.records.every(r => r.status === 'completed')).toBe(true);
    expect(persister.records.every(r => r.appId === appId)).toBe(true);

    // Final persisted state matches in-memory state (excluding metadata)
    const finalPersisted = await persister.load(partitionKey, appId);
    expect(finalPersisted).not.toBeNull();
    expect(finalPersisted!.state.dict).toEqual(state4.dict);
    expect(finalPersisted!.state.transformed).toEqual(state4.transformed);
    expect(finalPersisted!.state.doc).toEqual(state4.doc);
  });

  test('conditional transition is evaluated correctly', async () => {
    // The graph has basicAction → terminalAction when dict.foo === 0.
    // With foo=1 (the default), it should skip that branch and go to transformAction.
    // This is implicitly tested above, but let's be explicit.
    const persister = new InMemoryPersister();
    await persister.initialize();

    const app = await buildApplication(persister, 'pk', 'cond-test');
    const step1 = await app.step({ inputs: { userInput: 'test' } });
    expect(step1!.action.name).toBe('basicAction');

    // Rebuild and step — should go to transformAction, NOT terminalAction
    const app2 = await buildApplication(persister, 'pk', 'cond-test');
    const step2 = await app2.step();
    expect(step2!.action.name).toBe('transformAction');
  });

  test('run to completion without rebuilding', async () => {
    const persister = new InMemoryPersister();
    await persister.initialize();

    const graph = buildGraph();
    const state = createState(StateSchema, {});

    const app = new ApplicationBuilder()
      .withGraph(graph)
      .withEntrypoint('basicAction')
      .withState(state)
      .withIdentifiers('run-test', 'pk')
      .withStatePersister(persister)
      .build();

    const result = await app.run({
      inputs: { userInput: 'world' },
      haltAfter: ['terminalAction'],
    });

    expect(result.action!.name).toBe('terminalAction');
    expect(result.result).toEqual({ output: 'foo: 1, bar: true' });
    expect((result.state.data as any).dict.input).toBe('world');
    expect(persister.records.length).toBe(4);
  });

  test('iterate yields each step', async () => {
    const persister = new InMemoryPersister();
    await persister.initialize();

    const graph = buildGraph();
    const state = createState(StateSchema, {});

    const app = new ApplicationBuilder()
      .withGraph(graph)
      .withEntrypoint('basicAction')
      .withState(state)
      .withIdentifiers('iter-test', 'pk')
      .withStatePersister(persister)
      .build();

    const actionNames: string[] = [];
    for await (const step of app.iterate({
      inputs: { userInput: 'iter' },
      haltAfter: ['terminalAction'],
    })) {
      actionNames.push(step.action.name!);
    }

    expect(actionNames).toEqual([
      'basicAction',
      'transformAction',
      'formatAction',
      'terminalAction',
    ]);
  });

  test('serde round-trip preserves complex types', async () => {
    // Verify that Date, nested objects, arrays, and null survive
    // the serialize → persist → deserialize cycle
    const persister = new InMemoryPersister();
    await persister.initialize();

    const complexAction = action({
      reads: z.object({}),
      writes: z.object({
        nested: z.object({ a: z.number(), b: z.array(z.string()) }),
        timestamp: z.string(),
        items: z.array(z.number()),
        empty: z.null(),
      }),
      update: ({ state }) =>
        state.update({
          nested: { a: 42, b: ['x', 'y'] },
          timestamp: '2025-01-01T00:00:00.000Z',
          items: [1, 2, 3],
          empty: null,
        }),
    });

    const graph = new GraphBuilder()
      .withActions({ complexAction })
      .withTransitions(['complexAction', null])
      .build();

    const app = new ApplicationBuilder()
      .withGraph(graph)
      .withEntrypoint('complexAction')
      .withState(createState(z.object({}), {}))
      .withIdentifiers('serde-test', 'pk')
      .withStatePersister(persister)
      .build();

    await app.step();

    // Rebuild from persistence
    const defaultState = createState(z.object({}), {});
    const builder = await new ApplicationBuilder()
      .withGraph(graph)
      .initializeFrom({
        loader: persister,
        partitionKey: 'pk',
        appId: 'serde-test',
        defaultState,
        defaultEntrypoint: 'complexAction',
        resumeAtNextAction: true,
      });

    const restored = builder.build();
    const data = restored.state.data as any;

    expect(data.nested).toEqual({ a: 42, b: ['x', 'y'] });
    expect(data.timestamp).toBe('2025-01-01T00:00:00.000Z');
    expect(data.items).toEqual([1, 2, 3]);
    expect(data.empty).toBeNull();
  });

  test('partition key isolation', async () => {
    const persister = new InMemoryPersister();
    await persister.initialize();

    const graph = buildGraph();

    // Run two apps with different partition keys
    for (const pk of ['user-1', 'user-2']) {
      const app = new ApplicationBuilder()
        .withGraph(graph)
        .withEntrypoint('basicAction')
        .withState(createState(StateSchema, {}))
        .withIdentifiers('same-app-id', pk)
        .withStatePersister(persister)
        .build();

      await app.step({ inputs: { userInput: pk } });
    }

    // Each partition key should have its own state
    const state1 = await persister.load('user-1', 'same-app-id');
    const state2 = await persister.load('user-2', 'same-app-id');
    expect(state1!.state.dict.input).toBe('user-1');
    expect(state2!.state.dict.input).toBe('user-2');
  });
});
