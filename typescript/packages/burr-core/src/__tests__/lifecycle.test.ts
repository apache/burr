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
 * Lifecycle Hooks Tests
 *
 * Tests for:
 * - LifecycleAdapterSet dispatch
 * - PreRunStepHook / PostRunStepHook wired into Application.step()
 * - PostApplicationCreateHook wired into ApplicationBuilder.buildAsync()
 * - Error handling (hook failures, action failures with hooks)
 */

import { z } from 'zod';
import { action, createState, GraphBuilder, ApplicationBuilder } from '../index';
import {
  LifecycleAdapterSet,
  type LifecycleAdapter,
  type PreRunStepParams,
  type PostRunStepParams,
  type PostApplicationCreateParams,
} from '../lifecycle';

// ============================================================================
// Test Fixtures
// ============================================================================

const counter = action({
  reads: z.object({ count: z.number() }),
  writes: z.object({ count: z.number() }),
  update: ({ state }) => state.update({ count: state.count + 1 }),
});

const failingAction = action({
  reads: z.object({ count: z.number() }),
  writes: z.object({ count: z.number() }),
  run: async () => {
    throw new Error('action failed');
  },
  result: z.object({}),
  update: ({ state }) => state,
});

function buildCounterApp(adapters: LifecycleAdapter[] = []) {
  const graph = new GraphBuilder()
    .withActions({ counter })
    .withTransitions(['counter', 'counter'])
    .build();

  return new ApplicationBuilder()
    .withGraph(graph)
    .withState(createState(z.object({ count: z.number() }), { count: 0 }))
    .withEntrypoint('counter')
    .withHooks(...adapters)
    .build();
}

// ============================================================================
// LifecycleAdapterSet - Unit Tests
// ============================================================================

describe('LifecycleAdapterSet', () => {
  test('calls all preRunStep hooks in order', async () => {
    const order: number[] = [];
    const adapter1: LifecycleAdapter = {
      async preRunStep() { order.push(1); },
    };
    const adapter2: LifecycleAdapter = {
      async preRunStep() { order.push(2); },
    };

    const set = new LifecycleAdapterSet([adapter1, adapter2]);
    await set.callPreRunStep({
      appId: 'test',
      partitionKey: undefined,
      sequenceId: 1,
      state: {} as any,
      action: {} as any,
      inputs: {},
    });

    expect(order).toEqual([1, 2]);
  });

  test('calls all postRunStep hooks in order', async () => {
    const order: number[] = [];
    const adapter1: LifecycleAdapter = {
      async postRunStep() { order.push(1); },
    };
    const adapter2: LifecycleAdapter = {
      async postRunStep() { order.push(2); },
    };

    const set = new LifecycleAdapterSet([adapter1, adapter2]);
    await set.callPostRunStep({
      appId: 'test',
      partitionKey: undefined,
      sequenceId: 1,
      state: {} as any,
      action: {} as any,
      result: null,
      exception: null,
    });

    expect(order).toEqual([1, 2]);
  });

  test('skips adapters that do not implement the hook', async () => {
    const called: string[] = [];
    const preOnly: LifecycleAdapter = {
      async preRunStep() { called.push('pre'); },
    };
    const postOnly: LifecycleAdapter = {
      async postRunStep() { called.push('post'); },
    };

    const set = new LifecycleAdapterSet([preOnly, postOnly]);
    await set.callPreRunStep({
      appId: 'test', partitionKey: undefined, sequenceId: 1,
      state: {} as any, action: {} as any, inputs: {},
    });

    expect(called).toEqual(['pre']);
  });

  test('collects errors from hooks without stopping dispatch', async () => {
    const called: number[] = [];
    const adapter1: LifecycleAdapter = {
      async preRunStep() { called.push(1); throw new Error('hook1 failed'); },
    };
    const adapter2: LifecycleAdapter = {
      async preRunStep() { called.push(2); },
    };

    const set = new LifecycleAdapterSet([adapter1, adapter2]);
    await expect(set.callPreRunStep({
      appId: 'test', partitionKey: undefined, sequenceId: 1,
      state: {} as any, action: {} as any, inputs: {},
    })).rejects.toThrow('1 preRunStep hook(s) failed');

    // Both hooks were called despite first throwing
    expect(called).toEqual([1, 2]);
  });

  test('empty adapter set dispatches without error', async () => {
    const set = new LifecycleAdapterSet([]);
    await set.callPreRunStep({
      appId: 'test', partitionKey: undefined, sequenceId: 1,
      state: {} as any, action: {} as any, inputs: {},
    });
    // No error thrown
  });
});

// ============================================================================
// Application Integration - PreRunStep / PostRunStep
// ============================================================================

describe('Lifecycle hooks wired into Application.step()', () => {
  test('preRunStep is called before action execution', async () => {
    const hookCalls: PreRunStepParams[] = [];
    const adapter: LifecycleAdapter = {
      async preRunStep(params) { hookCalls.push(params); },
    };

    const app = buildCounterApp([adapter]);
    await app.step();

    expect(hookCalls).toHaveLength(1);
    expect(hookCalls[0].action.name).toBe('counter');
    expect(hookCalls[0].sequenceId).toBe(1);
  });

  test('postRunStep is called after successful action execution', async () => {
    const hookCalls: PostRunStepParams[] = [];
    const adapter: LifecycleAdapter = {
      async postRunStep(params) { hookCalls.push(params); },
    };

    const app = buildCounterApp([adapter]);
    await app.step();

    expect(hookCalls).toHaveLength(1);
    expect(hookCalls[0].action.name).toBe('counter');
    expect(hookCalls[0].exception).toBeNull();
    expect(hookCalls[0].sequenceId).toBe(1);
  });

  test('postRunStep receives exception when action fails', async () => {
    const hookCalls: PostRunStepParams[] = [];
    const adapter: LifecycleAdapter = {
      async postRunStep(params) { hookCalls.push(params); },
    };

    const graph = new GraphBuilder()
      .withActions({ failingAction })
      .withTransitions(['failingAction', 'failingAction'])
      .build();

    const app = new ApplicationBuilder()
      .withGraph(graph)
      .withState(createState(z.object({ count: z.number() }), { count: 0 }))
      .withEntrypoint('failingAction')
      .withHooks(adapter)
      .build();

    await expect(app.step()).rejects.toThrow('action failed');

    expect(hookCalls).toHaveLength(1);
    expect(hookCalls[0].exception).toBeInstanceOf(Error);
    expect(hookCalls[0].exception!.message).toBe('action failed');
    expect(hookCalls[0].result).toBeNull();
  });

  test('hooks fire on each step during iterate()', async () => {
    const preCalls: string[] = [];
    const postCalls: string[] = [];
    const adapter: LifecycleAdapter = {
      async preRunStep({ action }) { preCalls.push(action.name!); },
      async postRunStep({ action }) { postCalls.push(action.name!); },
    };

    const app = buildCounterApp([adapter]);

    let stepCount = 0;
    for await (const _step of app.iterate()) {
      stepCount++;
      if (stepCount >= 3) break;
    }

    expect(preCalls).toEqual(['counter', 'counter', 'counter']);
    expect(postCalls).toEqual(['counter', 'counter', 'counter']);
  });

  test('multiple adapters are all called', async () => {
    const calls: string[] = [];
    const adapter1: LifecycleAdapter = {
      async preRunStep() { calls.push('adapter1'); },
    };
    const adapter2: LifecycleAdapter = {
      async preRunStep() { calls.push('adapter2'); },
    };

    const app = buildCounterApp([adapter1, adapter2]);
    await app.step();

    expect(calls).toEqual(['adapter1', 'adapter2']);
  });

  test('preRunStep receives correct appId and partitionKey', async () => {
    let capturedParams: PreRunStepParams | null = null;
    const adapter: LifecycleAdapter = {
      async preRunStep(params) { capturedParams = params; },
    };

    const graph = new GraphBuilder()
      .withActions({ counter })
      .withTransitions(['counter', 'counter'])
      .build();

    const app = new ApplicationBuilder()
      .withGraph(graph)
      .withState(createState(z.object({ count: z.number() }), { count: 0 }))
      .withEntrypoint('counter')
      .withIdentifiers('my-app', 'my-partition')
      .withHooks(adapter)
      .build();

    await app.step();

    expect(capturedParams!.appId).toBe('my-app');
    expect(capturedParams!.partitionKey).toBe('my-partition');
  });
});

// ============================================================================
// PostApplicationCreateHook
// ============================================================================

describe('PostApplicationCreateHook via buildAsync()', () => {
  test('postApplicationCreate is called on buildAsync', async () => {
    const hookCalls: PostApplicationCreateParams[] = [];
    const adapter: LifecycleAdapter = {
      async postApplicationCreate(params) { hookCalls.push(params); },
    };

    const graph = new GraphBuilder()
      .withActions({ counter })
      .withTransitions(['counter', 'counter'])
      .build();

    await new ApplicationBuilder()
      .withGraph(graph)
      .withState(createState(z.object({ count: z.number() }), { count: 0 }))
      .withEntrypoint('counter')
      .withIdentifiers('test-app')
      .withHooks(adapter)
      .buildAsync();

    expect(hookCalls).toHaveLength(1);
    expect(hookCalls[0].appId).toBe('test-app');
    expect(hookCalls[0].entrypoint).toBe('counter');
  });

  test('buildAsync propagates postApplicationCreate errors', async () => {
    const adapter: LifecycleAdapter = {
      async postApplicationCreate() { throw new Error('create hook failed'); },
    };

    const graph = new GraphBuilder()
      .withActions({ counter })
      .withTransitions(['counter', 'counter'])
      .build();

    await expect(
      new ApplicationBuilder()
        .withGraph(graph)
        .withState(createState(z.object({ count: z.number() }), { count: 0 }))
        .withEntrypoint('counter')
        .withHooks(adapter)
        .buildAsync()
    ).rejects.toThrow('postApplicationCreate hook(s) failed');
  });
});

// ============================================================================
// withHooks() Builder API
// ============================================================================

describe('ApplicationBuilder.withHooks()', () => {
  test('withHooks accumulates adapters across multiple calls', async () => {
    const calls: string[] = [];
    const adapter1: LifecycleAdapter = {
      async preRunStep() { calls.push('a1'); },
    };
    const adapter2: LifecycleAdapter = {
      async preRunStep() { calls.push('a2'); },
    };

    const graph = new GraphBuilder()
      .withActions({ counter })
      .withTransitions(['counter', 'counter'])
      .build();

    const app = new ApplicationBuilder()
      .withGraph(graph)
      .withState(createState(z.object({ count: z.number() }), { count: 0 }))
      .withEntrypoint('counter')
      .withHooks(adapter1)
      .withHooks(adapter2)
      .build();

    await app.step();
    expect(calls).toEqual(['a1', 'a2']);
  });

  test('application works normally without any hooks', async () => {
    const app = buildCounterApp();
    const result = await app.step();
    expect(result).not.toBeNull();
    expect(result!.state.count).toBe(1);
  });
});
