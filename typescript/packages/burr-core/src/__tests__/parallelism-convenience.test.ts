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
 * Tests for MapActionsAndStates, MapActions, MapStates convenience classes.
 */

import { z } from 'zod';
import { action, createState, GraphBuilder } from '../index';
import {
  MapActionsAndStates,
  MapActions,
  MapStates,
  RunnableGraph,
  type ApplicationContext,
} from '../parallelism';
import { StateInstance } from '../state';
import { type ActionLike } from '../types';

// ============================================================================
// Test Fixtures
// ============================================================================

const doubler = action({
  reads: z.object({ value: z.number() }),
  writes: z.object({ value: z.number() }),
  update: ({ state }) => state.update({ value: state.value * 2 }),
});

const tripler = action({
  reads: z.object({ value: z.number() }),
  writes: z.object({ value: z.number() }),
  update: ({ state }) => state.update({ value: state.value * 3 }),
});

const testContext: ApplicationContext = {
  appId: 'parent-app',
  partitionKey: 'test-pk',
  sequenceId: 1,
};

// ============================================================================
// MapActionsAndStates
// ============================================================================

describe('MapActionsAndStates', () => {
  test('cartesian product of actions x states', async () => {
    class DoublerTripler extends MapActionsAndStates {
      get reads() { return ['values'] as const; }
      get writes() { return ['results'] as const; }

      actions(): (ActionLike<any, any, any, any>)[] {
        return [doubler, tripler];
      }

      states(
        state: StateInstance<any, any, any>,
      ): StateInstance<any, any, any>[] {
        const values: number[] = state.values;
        return values.map((v: number) =>
          createState(z.object({ value: z.number() }), { value: v })
        );
      }

      reduce(
        state: StateInstance<any, any, any>,
        resultStates: StateInstance<any, any, any>[]
      ): StateInstance<any, any, any> {
        return state.update({ results: resultStates.map(s => s.value) });
      }
    }

    const parallelAction = new DoublerTripler();
    const state = createState(
      z.object({ values: z.array(z.number()), results: z.array(z.number()).optional() }),
      { values: [2, 5] }
    );

    const { state: finalState } = await parallelAction.execute(state, testContext);
    // 2 actions x 2 states = 4 results
    // doubler(2)=4, doubler(5)=10, tripler(2)=6, tripler(5)=15
    expect([...finalState.results].sort((a: number, b: number) => a - b)).toEqual([4, 6, 10, 15]);
  });
});

// ============================================================================
// MapActions
// ============================================================================

describe('MapActions', () => {
  test('runs multiple actions over same state', async () => {
    class MultiTransform extends MapActions {
      get reads() { return ['value'] as const; }
      get writes() { return ['results'] as const; }

      actions(): ActionLike<any, any, any, any>[] {
        return [doubler, tripler];
      }

      reduce(
        state: StateInstance<any, any, any>,
        resultStates: StateInstance<any, any, any>[]
      ): StateInstance<any, any, any> {
        return state.update({ results: resultStates.map(s => s.value) });
      }
    }

    const parallelAction = new MultiTransform();
    const state = createState(
      z.object({ value: z.number(), results: z.array(z.number()).optional() }),
      { value: 10 }
    );

    const { state: finalState } = await parallelAction.execute(state, testContext);
    // doubler(10)=20, tripler(10)=30
    expect(finalState.results.sort()).toEqual([20, 30]);
  });

  test('state() override transforms input state', async () => {
    class TransformFirst extends MapActions {
      get reads() { return ['value'] as const; }
      get writes() { return ['results'] as const; }

      actions(): ActionLike<any, any, any, any>[] {
        return [doubler];
      }

      // Override state to modify before passing to action
      state(
        state: StateInstance<any, any, any>,
      ): StateInstance<any, any, any> {
        return state.update({ value: state.value + 100 });
      }

      reduce(
        state: StateInstance<any, any, any>,
        resultStates: StateInstance<any, any, any>[]
      ): StateInstance<any, any, any> {
        return state.update({ results: resultStates.map(s => s.value) });
      }
    }

    const parallelAction = new TransformFirst();
    const state = createState(
      z.object({ value: z.number(), results: z.array(z.number()).optional() }),
      { value: 5 }
    );

    const { state: finalState } = await parallelAction.execute(state, testContext);
    // state.value was 5, transformed to 105, doubled to 210
    expect(finalState.results).toEqual([210]);
  });
});

// ============================================================================
// MapStates
// ============================================================================

describe('MapStates', () => {
  test('runs single action over multiple state variants', async () => {
    class BatchDouble extends MapStates {
      get reads() { return ['items'] as const; }
      get writes() { return ['results'] as const; }

      action(): ActionLike<any, any, any, any> {
        return doubler;
      }

      states(
        state: StateInstance<any, any, any>,
      ): StateInstance<any, any, any>[] {
        const items: number[] = state.items;
        return items.map(v =>
          createState(z.object({ value: z.number() }), { value: v })
        );
      }

      reduce(
        state: StateInstance<any, any, any>,
        resultStates: StateInstance<any, any, any>[]
      ): StateInstance<any, any, any> {
        return state.update({ results: resultStates.map(s => s.value) });
      }
    }

    const parallelAction = new BatchDouble();
    const state = createState(
      z.object({ items: z.array(z.number()), results: z.array(z.number()).optional() }),
      { items: [1, 2, 3, 4] }
    );

    const { state: finalState } = await parallelAction.execute(state, testContext);
    expect(finalState.results).toEqual([2, 4, 6, 8]);
  });
});

// ============================================================================
// SubGraphTask persistence cascading
// ============================================================================

describe('SubGraphTask persistence cascading', () => {
  test('SubGraphTask cascades persister from parent context', async () => {
    const { InMemoryPersister } = await import('../persistence');
    const persister = new InMemoryPersister();
    await persister.initialize();

    const graph = new GraphBuilder()
      .withActions({ doubler })
      .withTransitions(['doubler', null])
      .build();

    const runnable = RunnableGraph.create(graph, 'doubler', ['doubler']);

    const { SubGraphTask } = await import('../parallelism');
    const task = new SubGraphTask({
      graph: runnable,
      state: createState(z.object({ value: z.number() }), { value: 5 }),
      applicationId: 'child-with-persist',
    });

    // Parent context has a persister
    const context: ApplicationContext = {
      appId: 'parent',
      partitionKey: 'pk',
      sequenceId: 1,
      statePersister: persister,
    };

    await task.run(context);

    // The child app should have cascaded the persister
    expect(persister.records.length).toBeGreaterThan(0);
    expect(persister.records[0].appId).toBe('child-with-persist');
  });
});
