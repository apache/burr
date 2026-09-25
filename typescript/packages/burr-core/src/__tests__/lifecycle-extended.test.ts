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
 * Extended lifecycle hook tests: execute-call hooks and stream hooks.
 */

import { z } from 'zod';
import { action, createState, GraphBuilder, ApplicationBuilder } from '../index';
import { streamingAction } from '../streaming';
import {
  type LifecycleAdapter,
  type ExecuteMethod,
  type PostStreamItemParams,
} from '../lifecycle';

// ============================================================================
// Test Fixtures
// ============================================================================

const counter = action({
  reads: z.object({ count: z.number() }),
  writes: z.object({ count: z.number() }),
  update: ({ state }) => state.update({ count: state.count + 1 }),
});

// ============================================================================
// Execute-call hooks
// ============================================================================

describe('PreExecuteCall / PostExecuteCall hooks', () => {
  test('step() fires pre/post execute-call hooks', async () => {
    const methods: ExecuteMethod[] = [];
    const adapter: LifecycleAdapter = {
      async preExecuteCall({ method }) { methods.push(method); },
      async postExecuteCall({ method }) { methods.push(method); },
    };

    const graph = new GraphBuilder()
      .withActions({ counter })
      .withTransitions(['counter', 'counter'])
      .build();

    const app = new ApplicationBuilder()
      .withGraph(graph)
      .withState(createState(z.object({ count: z.number() }), { count: 0 }))
      .withEntrypoint('counter')
      .withHooks(adapter)
      .build();

    await app.step();
    expect(methods).toEqual(['step', 'step']);
  });

  test('run() fires pre/post execute-call hooks once', async () => {
    const calls: string[] = [];
    const adapter: LifecycleAdapter = {
      async preExecuteCall({ method }) { calls.push(`pre:${method}`); },
      async postExecuteCall({ method }) { calls.push(`post:${method}`); },
    };

    const graph = new GraphBuilder()
      .withActions({ counter })
      .withTransitions(
        ['counter', 'counter', (s: any) => s.count < 3],
        ['counter', null, (s: any) => s.count >= 3]
      )
      .build();

    const app = new ApplicationBuilder()
      .withGraph(graph)
      .withState(createState(z.object({ count: z.number() }), { count: 0 }))
      .withEntrypoint('counter')
      .withHooks(adapter)
      .build();

    await app.run();
    // run() fires execute-call hooks once (not per step)
    expect(calls).toEqual(['pre:run', 'post:run']);
  });

  test('iterate() fires pre/post execute-call hooks once', async () => {
    const calls: string[] = [];
    const adapter: LifecycleAdapter = {
      async preExecuteCall({ method }) { calls.push(`pre:${method}`); },
      async postExecuteCall({ method }) { calls.push(`post:${method}`); },
    };

    const graph = new GraphBuilder()
      .withActions({ counter })
      .withTransitions(['counter', 'counter'])
      .build();

    const app = new ApplicationBuilder()
      .withGraph(graph)
      .withState(createState(z.object({ count: z.number() }), { count: 0 }))
      .withEntrypoint('counter')
      .withHooks(adapter)
      .build();

    let stepCount = 0;
    for await (const _step of app.iterate()) {
      stepCount++;
      if (stepCount >= 2) break;
    }

    expect(calls).toEqual(['pre:iterate', 'post:iterate']);
  });

  test('postExecuteCall receives exception on failure', async () => {
    let capturedError: Error | null = null;
    const adapter: LifecycleAdapter = {
      async postExecuteCall({ exception }) { capturedError = exception; },
    };

    const failingAction = action({
      reads: z.object({ count: z.number() }),
      writes: z.object({ count: z.number() }),
      result: z.object({}),
      run: async () => { throw new Error('boom'); },
      update: ({ state }) => state,
    });

    const graph = new GraphBuilder()
      .withActions({ failingAction })
      .withTransitions(['failingAction', null])
      .build();

    const app = new ApplicationBuilder()
      .withGraph(graph)
      .withState(createState(z.object({ count: z.number() }), { count: 0 }))
      .withEntrypoint('failingAction')
      .withHooks(adapter)
      .build();

    await expect(app.step()).rejects.toThrow('boom');
    expect(capturedError).toBeInstanceOf(Error);
    expect(capturedError!.message).toContain('boom');
  });
});

// ============================================================================
// Stream hooks
// ============================================================================

describe('Stream lifecycle hooks', () => {
  test('streaming action fires preStartStream, postStreamItem, postEndStream', async () => {
    const events: string[] = [];
    const items: PostStreamItemParams[] = [];
    const adapter: LifecycleAdapter = {
      async preStartStream() { events.push('preStartStream'); },
      async postStreamItem(params) { events.push(`item:${params.itemIndex}`); items.push(params); },
      async postEndStream() { events.push('postEndStream'); },
    };

    const streamCounter = streamingAction({
      reads: z.object({ count: z.number() }),
      writes: z.object({ count: z.number(), tokens: z.string() }),
      result: z.object({ token: z.string(), accumulated: z.string() }),
      async *streamRun() {
        yield { token: 'a', accumulated: 'a' };
        yield { token: 'b', accumulated: 'ab' };
        yield { token: 'c', accumulated: 'abc' };
      },
      update: ({ result, state }) =>
        state.update({ count: state.count + 1, tokens: result.accumulated }),
    });

    const graph = new GraphBuilder()
      .withActions({ streamCounter })
      .withTransitions(['streamCounter', null])
      .build();

    const app = new ApplicationBuilder()
      .withGraph(graph)
      .withState(
        createState(
          z.object({ count: z.number(), tokens: z.string().optional() }),
          { count: 0 }
        )
      )
      .withEntrypoint('streamCounter')
      .withHooks(adapter)
      .build();

    const result = await app.streamStep();
    expect(result).not.toBeNull();

    // Consume the stream
    for await (const _chunk of result!.stream) { /* consume */ }
    await result!.stream.get();

    expect(events).toEqual([
      'preStartStream',
      'item:0',
      'item:1',
      'item:2',
      'postEndStream',
    ]);

    // Verify item params
    expect(items[0].item.token).toBe('a');
    expect(items[0].itemIndex).toBe(0);
    expect(items[0].streamInitializeTime).toBeInstanceOf(Date);
    expect(items[1].firstStreamItemStartTime).toBeInstanceOf(Date);
  });
});
