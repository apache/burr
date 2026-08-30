/**
 * Copyright (c) 2024-2025 Elijah ben Izzy
 * SPDX-License-Identifier: Apache-2.0
 */

import { z } from 'zod';
import { action } from '../action';
import { GraphBuilder } from '../graph';
import { ApplicationBuilder } from '../application-builder';
import { Application } from '../application';
import { createState } from '../state';

describe('ApplicationBuilder', () => {
  // Test fixtures
  const action1 = action({
    reads: z.object({ count: z.number() }),
    writes: z.object({ count: z.number() }),
    update: ({ state }) => state.update({ count: state.count + 1 })
  });

  const action2 = action({
    reads: z.object({ count: z.number() }),
    writes: z.object({ done: z.boolean() }),
    update: ({ state }) => state.update({ done: true })
  });

  const testGraph = new GraphBuilder()
    .withActions({ action1, action2 })
    .withTransitions(['action1', 'action2'])
    .build();

  const testState = createState(
    z.object({ count: z.number(), done: z.boolean() }),
    { count: 0, done: false }
  );

  describe('withGraph', () => {
    test('sets the graph', () => {
      const builder = new ApplicationBuilder().withGraph(testGraph);
      const app = builder.withEntrypoint('action1').withState(testState).build();
      
      expect(app.graph).toBe(testGraph);
    });

    test('throws if graph already set', () => {
      const builder = new ApplicationBuilder().withGraph(testGraph);
      
      expect(() => {
        builder.withGraph(testGraph);
      }).toThrow('Graph is already set');
    });

    test('returns new builder instance (immutable)', () => {
      const builder1 = new ApplicationBuilder();
      const builder2 = builder1.withGraph(testGraph);
      
      expect(builder1).not.toBe(builder2);
    });
  });

  describe('withEntrypoint', () => {
    test('sets the entrypoint', () => {
      const builder = new ApplicationBuilder()
        .withGraph(testGraph)
        .withEntrypoint('action1');
      
      const app = builder.withState(testState).build();
      expect(app.entrypoint).toBe('action1');
    });

    test('throws if entrypoint already set', () => {
      const builder = new ApplicationBuilder()
        .withGraph(testGraph)
        .withEntrypoint('action1');
      
      expect(() => {
        builder.withEntrypoint('action2');
      }).toThrow('Entrypoint is already set');
    });

    test('throws if graph not set', () => {
      const builder = new ApplicationBuilder();
      
      expect(() => {
        builder.withEntrypoint('action1');
      }).toThrow('Graph must be set before entrypoint');
    });

    test('throws if entrypoint action not in graph', () => {
      const builder = new ApplicationBuilder().withGraph(testGraph);
      
      expect(() => {
        builder.withEntrypoint('nonexistent');
      }).toThrow("Entrypoint action 'nonexistent' not found in graph");
    });

    test('returns new builder instance (immutable)', () => {
      const builder1 = new ApplicationBuilder().withGraph(testGraph);
      const builder2 = builder1.withEntrypoint('action1');
      
      expect(builder1).not.toBe(builder2);
    });
  });

  describe('withState', () => {
    test('throws if state already set', () => {
      const builder = new ApplicationBuilder()
        .withGraph(testGraph)
        .withEntrypoint('action1')
        .withState(testState);
      
      expect(() => {
        builder.withState(testState);
      }).toThrow('Initial state is already set');
    });

    test('returns new builder instance (immutable)', () => {
      const builder1 = new ApplicationBuilder()
        .withGraph(testGraph)
        .withEntrypoint('action1');
      const builder2 = builder1.withState(testState);
      
      expect(builder1).not.toBe(builder2);
    });
  });

  describe('build', () => {
    test('creates application with all components', () => {
      const app = new ApplicationBuilder()
        .withGraph(testGraph)
        .withEntrypoint('action1')
        .withState(testState)
        .build();
      
      expect(app).toBeInstanceOf(Application);
      expect(app.graph).toBe(testGraph);
      expect(app.entrypoint).toBe('action1');
    });

    test('throws if graph not set', () => {
      const builder = new ApplicationBuilder();
      
      expect(() => {
        builder.build();
      }).toThrow('Cannot build application without graph');
    });

    test('throws if entrypoint not set', () => {
      const builder = new ApplicationBuilder().withGraph(testGraph);
      
      expect(() => {
        builder.build();
      }).toThrow('Cannot build application without entrypoint');
    });

    test('throws if state not set', () => {
      const builder = new ApplicationBuilder()
        .withGraph(testGraph)
        .withEntrypoint('action1');
      
      expect(() => {
        builder.build();
      }).toThrow('Cannot build application without initial state');
    });
  });

  describe('method chaining', () => {
    test('can chain all methods in order', () => {
      const app = new ApplicationBuilder()
        .withGraph(testGraph)
        .withEntrypoint('action1')
        .withState(testState)
        .build();
      
      expect(app).toBeInstanceOf(Application);
    });

    test('can chain methods in different order', () => {
      const app = new ApplicationBuilder()
        .withGraph(testGraph)
        .withState(testState)
        .withEntrypoint('action1')
        .build();
      
      expect(app).toBeInstanceOf(Application);
    });

    test('state can be set before entrypoint', () => {
      const app = new ApplicationBuilder()
        .withGraph(testGraph)
        .withState(testState)
        .withEntrypoint('action1')
        .build();
      
      expect(app).toBeInstanceOf(Application);
    });
  });
});

describe('Application', () => {
  test('stores graph, entrypoint, and initial state', () => {
    const copyAction = action({
      reads: z.object({ x: z.number() }),
      writes: z.object({ y: z.number() }),
      update: ({ state }) => state.update({ y: state.x })
    });

    const graph = new GraphBuilder()
      .withActions({ copyAction })
      .build();

    const state = createState(
      z.object({ x: z.number(), y: z.number() }),
      { x: 5, y: 0 }
    );

    // Use ApplicationBuilder instead of direct construction (recommended pattern)
    const app = new ApplicationBuilder()
      .withGraph(graph)
      .withEntrypoint('copyAction')
      .withState(state)
      .build();

    expect(app.graph).toBe(graph);
    expect(app.entrypoint).toBe('copyAction');
  });
});

describe('Application.runStep (Fork→Launch→Gather→Commit)', () => {
  test('FORK phase: action receives only declared reads', async () => {
    // Action that only reads count, not name
    const counter = action({
      reads: z.object({ count: z.number() }),
      writes: z.object({ count: z.number() }),
      run: async ({ state }) => {
        // Should only have access to count, not name
        expect(state.data).toHaveProperty('count');
        expect(state.data).not.toHaveProperty('name');
        return {};
      },
      update: ({ state }) => state.update({ count: state.count + 1 })
    });

    const graph = new GraphBuilder()
      .withActions({ counter })
      .build();

    const initialState = createState(
      z.object({ count: z.number(), name: z.string() }),
      { count: 0, name: 'Alice' }
    );

    const app = new ApplicationBuilder()
      .withGraph(graph)
      .withEntrypoint('counter')
      .withState(initialState)
      .withIdentifiers('test-app')
      .build();

    await app.step();
  });

  test('COMMIT phase: preserves unwritten fields', async () => {
    // Action that writes count but not name
    const partialWriter = action({
      reads: z.object({ count: z.number() }),
      writes: z.object({ count: z.number() }),
      update: ({ state }) => state.update({ count: state.count + 1 })
    });

    const graph = new GraphBuilder()
      .withActions({ partialWriter })
      .build();

    const initialState = createState(
      z.object({ count: z.number(), name: z.string() }),
      { count: 0, name: 'Alice' }
    );

    const app = new ApplicationBuilder()
      .withGraph(graph)
      .withEntrypoint('partialWriter')
      .withState(initialState)
      .withIdentifiers('test-app')
      .build();

    const result = await app.step();

    // Verify count was updated
    expect(result?.state.data.count).toBe(1);
    // Verify name was preserved (not written by action)
    expect(result?.state.data.name).toBe('Alice');
  });

  test('COMMIT phase: merges writes into full state including metadata', async () => {
    const counter = action({
      reads: z.object({ count: z.number() }),
      writes: z.object({ count: z.number() }),
      update: ({ state }) => state.update({ count: state.count + 1 })
    });

    const graph = new GraphBuilder()
      .withActions({ counter })
      .build();

    const initialState = createState(
      z.object({ count: z.number() }),
      { count: 0 }
    );

    const app = new ApplicationBuilder()
      .withGraph(graph)
      .withEntrypoint('counter')
      .withState(initialState)
      .withIdentifiers('test-app', 'partition-1')
      .build();

    const result = await app.step();

    // Verify user state was updated
    expect(result?.state.data.count).toBe(1);
    
    // Verify metadata was preserved
    expect(result?.state.data.appMetadata).toEqual({
      appId: 'test-app',
      partitionKey: 'partition-1',
      entrypoint: 'counter'
    });
    
    expect(result?.state.data.executionMetadata.sequenceId).toBe(1);
    expect(result?.state.data.executionMetadata.priorStep).toBe('counter');
  });
});

describe('Application.commitWrites', () => {
  test('merges writes into committed state', () => {
    const counter = action({
      reads: z.object({ count: z.number() }),
      writes: z.object({ count: z.number() }),
      update: ({ state }) => state.update({ count: state.count + 1 })
    });

    const graph = new GraphBuilder()
      .withActions({ counter })
      .build();

    const committedState = createState(
      z.object({ count: z.number(), name: z.string() }),
      { count: 0, name: 'Alice' }
    );

    const app = new ApplicationBuilder()
      .withGraph(graph)
      .withEntrypoint('counter')
      .withState(committedState)
      .withIdentifiers('test-app')
      .build();

    const writes = createState(
      z.object({ count: z.number() }),
      { count: 1 }
    );

    // Access private method using bracket notation
    const merged = (app as any).commitWrites(app.state, writes, counter);

    // Verify count was updated
    expect(merged.data.count).toBe(1);
    // Verify name was preserved
    expect(merged.data.name).toBe('Alice');
    // Verify metadata was preserved
    expect(merged.data.appMetadata).toBeDefined();
  });

  test('rejects writes to reserved metadata keys', () => {
    const badAction = action({
      reads: z.object({ count: z.number() }),
      writes: z.object({ count: z.number() }),
      update: ({ state }) => state.update({ count: state.count + 1 })
    });

    const graph = new GraphBuilder()
      .withActions({ badAction })
      .build();

    const committedState = createState(
      z.object({ count: z.number() }),
      { count: 0 }
    );

    const app = new ApplicationBuilder()
      .withGraph(graph)
      .withEntrypoint('badAction')
      .withState(committedState)
      .withIdentifiers('test-app')
      .build();

    // Create writes that attempt to modify reserved metadata
    const badWrites = createState(
      z.object({ count: z.number(), appMetadata: z.any() }),
      { count: 1, appMetadata: { appId: 'hacked' } }
    );

    // Access private method using bracket notation
    expect(() => {
      (app as any).commitWrites(app.state, badWrites, badAction);
    }).toThrow(/reserved metadata keys/);
    expect(() => {
      (app as any).commitWrites(app.state, badWrites, badAction);
    }).toThrow(/appMetadata/);
  });

  test('rejects writes to any key ending in Metadata', () => {
    const badAction = action({
      reads: z.object({ count: z.number() }),
      writes: z.object({ count: z.number() }),
      update: ({ state }) => state.update({ count: state.count + 1 })
    });

    const graph = new GraphBuilder()
      .withActions({ badAction })
      .build();

    const committedState = createState(
      z.object({ count: z.number() }),
      { count: 0 }
    );

    const app = new ApplicationBuilder()
      .withGraph(graph)
      .withEntrypoint('badAction')
      .withState(committedState)
      .withIdentifiers('test-app')
      .build();

    // Try to write to custom metadata key
    const badWrites = createState(
      z.object({ count: z.number(), customMetadata: z.any() }),
      { count: 1, customMetadata: { foo: 'bar' } }
    );

    expect(() => {
      (app as any).commitWrites(app.state, badWrites, badAction);
    }).toThrow(/reserved metadata keys/);
    expect(() => {
      (app as any).commitWrites(app.state, badWrites, badAction);
    }).toThrow(/customMetadata/);
  });
});

