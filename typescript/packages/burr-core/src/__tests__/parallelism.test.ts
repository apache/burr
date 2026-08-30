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
import { action, createState, GraphBuilder } from '../index';
import {
  RunnableGraph,
  SubGraphTask,
  TaskBasedParallelAction,
  type ApplicationContext,
} from '../parallelism';
import { StateInstance } from '../state';

// ============================================================================
// Test Fixtures
// ============================================================================

const doubler = action({
  reads: z.object({ value: z.number() }),
  writes: z.object({ value: z.number() }),
  update: ({ state }) => state.update({ value: state.value * 2 }),
});

const adder = action({
  reads: z.object({ value: z.number() }),
  writes: z.object({ value: z.number() }),
  inputs: z.object({ amount: z.number() }),
  update: ({ state, inputs }) => state.update({ value: state.value + inputs.amount }),
});

function makeSimpleGraph() {
  return new GraphBuilder()
    .withActions({ doubler })
    .withTransitions(['doubler', null])
    .build();
}

const testContext: ApplicationContext = {
  appId: 'parent-app',
  partitionKey: 'test-pk',
  sequenceId: 1,
};

// ============================================================================
// RunnableGraph
// ============================================================================

describe('RunnableGraph', () => {
  test('create wraps graph with entrypoint and haltAfter', () => {
    const graph = makeSimpleGraph();
    const runnable = RunnableGraph.create(graph, 'doubler', ['doubler']);

    expect(runnable.graph).toBe(graph);
    expect(runnable.entrypoint).toBe('doubler');
    expect(runnable.haltAfter).toEqual(['doubler']);
  });
});

// ============================================================================
// SubGraphTask
// ============================================================================

describe('SubGraphTask', () => {
  test('runs a single-action graph to completion', async () => {
    const graph = makeSimpleGraph();
    const runnable = RunnableGraph.create(graph, 'doubler', ['doubler']);
    const state = createState(z.object({ value: z.number() }), { value: 5 });

    const task = new SubGraphTask({
      graph: runnable,
      state,
      applicationId: 'child-1',
    });

    const resultState = await task.run(testContext);
    expect(resultState.value).toBe(10);
  });

  test('runs with inputs', async () => {
    const graph = new GraphBuilder()
      .withActions({ adder })
      .withTransitions(['adder', null])
      .build();

    const runnable = RunnableGraph.create(graph, 'adder', ['adder']);
    const state = createState(z.object({ value: z.number() }), { value: 3 });

    const task = new SubGraphTask({
      graph: runnable,
      state,
      inputs: { amount: 7 },
      applicationId: 'child-2',
    });

    const resultState = await task.run(testContext);
    expect(resultState.value).toBe(10);
  });

  test('runs multi-step graph', async () => {
    const increment = action({
      reads: z.object({ count: z.number() }),
      writes: z.object({ count: z.number() }),
      update: ({ state }) => state.update({ count: state.count + 1 }),
    });

    const graph = new GraphBuilder()
      .withActions({ increment })
      .withTransitions(
        ['increment', 'increment', (s: any) => s.count < 3],
        ['increment', null, (s: any) => s.count >= 3]
      )
      .build();

    const runnable = RunnableGraph.create(graph, 'increment', []);
    const state = createState(z.object({ count: z.number() }), { count: 0 });

    const task = new SubGraphTask({
      graph: runnable,
      state,
      applicationId: 'child-multi',
    });

    const resultState = await task.run(testContext);
    expect(resultState.count).toBe(3);
  });
});

// ============================================================================
// TaskBasedParallelAction
// ============================================================================

describe('TaskBasedParallelAction', () => {
  test('executes multiple tasks in parallel and reduces', async () => {
    const graph = makeSimpleGraph();
    const runnable = RunnableGraph.create(graph, 'doubler', ['doubler']);

    class FanOutDoubler extends TaskBasedParallelAction {
      get reads() { return ['values'] as const; }
      get writes() { return ['results'] as const; }

      tasks(
        state: StateInstance<any, any, any>,
        context: ApplicationContext
      ): SubGraphTask[] {
        const values: number[] = state.values;
        return values.map((v: number, i: number) =>
          new SubGraphTask({
            graph: runnable,
            state: createState(z.object({ value: z.number() }), { value: v }),
            applicationId: `${context.appId}-child-${i}`,
          })
        );
      }

      reduce(
        state: StateInstance<any, any, any>,
        states: StateInstance<any, any, any>[]
      ): StateInstance<any, any, any> {
        const results = states.map(s => s.value);
        return state.update({ results });
      }
    }

    const parallelAction = new FanOutDoubler();
    const state = createState(
      z.object({ values: z.array(z.number()), results: z.array(z.number()).optional() }),
      { values: [1, 2, 3, 4, 5] }
    );

    const { state: finalState } = await parallelAction.execute(state, testContext);
    expect(finalState.results).toEqual([2, 4, 6, 8, 10]);
  });

  test('handles empty task list', async () => {
    class EmptyTasks extends TaskBasedParallelAction {
      get reads() { return [] as const; }
      get writes() { return [] as const; }

      tasks(): SubGraphTask[] {
        return [];
      }

      reduce(
        state: StateInstance<any, any, any>,
        _states: StateInstance<any, any, any>[]
      ): StateInstance<any, any, any> {
        return state;
      }
    }

    const parallelAction = new EmptyTasks();
    const state = createState(z.object({ x: z.number() }), { x: 42 });

    const { state: finalState } = await parallelAction.execute(state, testContext);
    expect(finalState.x).toBe(42);
  });

  test('tasks run concurrently (not sequentially)', async () => {
    // Create an action with a small delay to verify concurrent execution
    const slowAction = action({
      reads: z.object({ value: z.number() }),
      writes: z.object({ value: z.number() }),
      result: z.object({ computed: z.number() }),
      run: async ({ state }) => {
        await new Promise(r => setTimeout(r, 50));
        return { computed: state.value * 10 };
      },
      update: ({ result, state }) => state.update({ value: result.computed }),
    });

    const graph = new GraphBuilder()
      .withActions({ slowAction })
      .withTransitions(['slowAction', null])
      .build();

    const runnable = RunnableGraph.create(graph, 'slowAction', ['slowAction']);

    class ConcurrentTest extends TaskBasedParallelAction {
      get reads() { return [] as const; }
      get writes() { return ['results'] as const; }

      tasks(): SubGraphTask[] {
        return [1, 2, 3].map((v, i) =>
          new SubGraphTask({
            graph: runnable,
            state: createState(z.object({ value: z.number() }), { value: v }),
            applicationId: `concurrent-${i}`,
          })
        );
      }

      reduce(
        state: StateInstance<any, any, any>,
        states: StateInstance<any, any, any>[]
      ): StateInstance<any, any, any> {
        return state.update({ results: states.map(s => s.value) });
      }
    }

    const parallelAction = new ConcurrentTest();
    const state = createState(
      z.object({ results: z.array(z.number()).optional() }),
      {}
    );

    const start = Date.now();
    const { state: finalState } = await parallelAction.execute(state, testContext);
    const elapsed = Date.now() - start;

    expect(finalState.results).toEqual([10, 20, 30]);
    // If sequential: ~150ms. If concurrent: ~50ms. Allow margin.
    expect(elapsed).toBeLessThan(120);
  });
});
