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

import { z } from 'zod';
import { action, createState, GraphBuilder, ApplicationBuilder } from '../index';
import { InMemoryPersister } from '../persistence';

// ============================================================================
// Test Fixtures
// ============================================================================

const counter = action({
  reads: z.object({ count: z.number() }),
  writes: z.object({ count: z.number() }),
  update: ({ state }) => state.update({ count: state.count + 1 }),
});

// ============================================================================
// InMemoryPersister - Unit Tests
// ============================================================================

describe('InMemoryPersister', () => {
  test('save and load round-trip', async () => {
    const persister = new InMemoryPersister();
    await persister.initialize();

    await persister.save({
      partitionKey: 'pk',
      appId: 'app1',
      sequenceId: 1,
      position: 'counter',
      state: { count: 42 },
      status: 'completed',
    });

    const loaded = await persister.load('pk', 'app1');
    expect(loaded).not.toBeNull();
    expect(loaded!.state).toEqual({ count: 42 });
    expect(loaded!.sequenceId).toBe(1);
    expect(loaded!.position).toBe('counter');
    expect(loaded!.status).toBe('completed');
  });

  test('load returns latest completed state', async () => {
    const persister = new InMemoryPersister();

    await persister.save({
      partitionKey: 'pk', appId: 'app1', sequenceId: 1,
      position: 'a', state: { count: 1 }, status: 'completed',
    });
    await persister.save({
      partitionKey: 'pk', appId: 'app1', sequenceId: 2,
      position: 'b', state: { count: 2 }, status: 'completed',
    });
    await persister.save({
      partitionKey: 'pk', appId: 'app1', sequenceId: 3,
      position: 'c', state: { count: 3 }, status: 'failed',
    });

    const loaded = await persister.load('pk', 'app1');
    expect(loaded!.sequenceId).toBe(2); // Latest completed, not the failed one
  });

  test('load at specific sequenceId', async () => {
    const persister = new InMemoryPersister();

    await persister.save({
      partitionKey: 'pk', appId: 'app1', sequenceId: 1,
      position: 'a', state: { count: 1 }, status: 'completed',
    });
    await persister.save({
      partitionKey: 'pk', appId: 'app1', sequenceId: 2,
      position: 'b', state: { count: 2 }, status: 'completed',
    });

    const loaded = await persister.load('pk', 'app1', 1);
    expect(loaded!.state).toEqual({ count: 1 });
  });

  test('load returns null when not found', async () => {
    const persister = new InMemoryPersister();
    const loaded = await persister.load('pk', 'nonexistent');
    expect(loaded).toBeNull();
  });

  test('listAppIds returns unique app IDs for partition', async () => {
    const persister = new InMemoryPersister();

    await persister.save({
      partitionKey: 'pk1', appId: 'app1', sequenceId: 1,
      position: 'a', state: {}, status: 'completed',
    });
    await persister.save({
      partitionKey: 'pk1', appId: 'app2', sequenceId: 1,
      position: 'a', state: {}, status: 'completed',
    });
    await persister.save({
      partitionKey: 'pk2', appId: 'app3', sequenceId: 1,
      position: 'a', state: {}, status: 'completed',
    });

    const ids = await persister.listAppIds('pk1');
    expect(ids.sort()).toEqual(['app1', 'app2']);
  });

  test('clear removes all records', async () => {
    const persister = new InMemoryPersister();
    await persister.save({
      partitionKey: 'pk', appId: 'app1', sequenceId: 1,
      position: 'a', state: {}, status: 'completed',
    });

    persister.clear();
    expect(persister.records).toHaveLength(0);
    const loaded = await persister.load('pk', 'app1');
    expect(loaded).toBeNull();
  });
});

// ============================================================================
// PersisterHook - Integration with Application
// ============================================================================

describe('PersisterHook with Application', () => {
  test('saves state after each step', async () => {
    const persister = new InMemoryPersister();
    await persister.initialize();

    const graph = new GraphBuilder()
      .withActions({ counter })
      .withTransitions(['counter', 'counter'])
      .build();

    const app = new ApplicationBuilder()
      .withGraph(graph)
      .withState(createState(z.object({ count: z.number() }), { count: 0 }))
      .withEntrypoint('counter')
      .withIdentifiers('test-app', 'test-pk')
      .withStatePersister(persister)
      .build();

    await app.step();
    await app.step();

    expect(persister.records).toHaveLength(2);
    expect(persister.records[0].appId).toBe('test-app');
    expect(persister.records[0].position).toBe('counter');
    expect(persister.records[0].status).toBe('completed');
    expect(persister.records[1].sequenceId).toBeGreaterThan(persister.records[0].sequenceId);
  });

  test('saves with failed status when action throws', async () => {
    const persister = new InMemoryPersister();

    const failingAction = action({
      reads: z.object({ count: z.number() }),
      writes: z.object({ count: z.number() }),
      result: z.object({}),
      run: async () => { throw new Error('boom'); },
      update: ({ state }) => state,
    });

    const graph = new GraphBuilder()
      .withActions({ failingAction })
      .withTransitions(['failingAction', 'failingAction'])
      .build();

    const app = new ApplicationBuilder()
      .withGraph(graph)
      .withState(createState(z.object({ count: z.number() }), { count: 0 }))
      .withEntrypoint('failingAction')
      .withStatePersister(persister)
      .build();

    await expect(app.step()).rejects.toThrow('boom');

    expect(persister.records).toHaveLength(1);
    expect(persister.records[0].status).toBe('failed');
  });
});

// ============================================================================
// initializeFrom
// ============================================================================

describe('ApplicationBuilder.initializeFrom()', () => {
  test('loads persisted state and resumes', async () => {
    const persister = new InMemoryPersister();

    // Save some state
    await persister.save({
      partitionKey: 'pk', appId: 'app1', sequenceId: 3,
      position: 'counter', state: { count: 10 }, status: 'completed',
    });

    const graph = new GraphBuilder()
      .withActions({ counter })
      .withTransitions(['counter', 'counter'])
      .build();

    const defaultState = createState(z.object({ count: z.number() }), { count: 0 });

    const builder = await new ApplicationBuilder()
      .withGraph(graph)
      .initializeFrom({
        loader: persister,
        partitionKey: 'pk',
        appId: 'app1',
        defaultState,
        defaultEntrypoint: 'counter',
        resumeAtNextAction: true,
      });

    // initializeFrom already sets entrypoint from defaultEntrypoint
    const app = builder.build();

    // State should be loaded from persistence
    expect(app.state.count).toBe(10);
  });

  test('falls back to defaults when no persisted state', async () => {
    const persister = new InMemoryPersister();

    const graph = new GraphBuilder()
      .withActions({ counter })
      .withTransitions(['counter', 'counter'])
      .build();

    const defaultState = createState(z.object({ count: z.number() }), { count: 0 });

    const builder = await new ApplicationBuilder()
      .withGraph(graph)
      .initializeFrom({
        loader: persister,
        partitionKey: 'pk',
        appId: 'nonexistent',
        defaultState,
        defaultEntrypoint: 'counter',
      });

    const app = builder.build();
    expect(app.state.count).toBe(0);
  });
});
