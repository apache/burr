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
 * Streaming Actions Tests
 *
 * Tests for:
 * - StreamingAction class and streamingAction() factory
 * - StreamingResultContainer iteration and .get()
 * - Application.streamStep() with streaming and non-streaming actions
 * - Integration with lifecycle hooks
 */

import { z } from 'zod';
import { action, createState, GraphBuilder, ApplicationBuilder } from '../index';
import {
  StreamingAction,
  streamingAction,
  StreamingResultContainer,
  isStreamingAction,
} from '../streaming';

// ============================================================================
// StreamingAction Unit Tests
// ============================================================================

describe('StreamingAction', () => {
  test('streamingAction factory creates a StreamingAction', () => {
    const sa = streamingAction({
      reads: z.object({ prompt: z.string() }),
      writes: z.object({ response: z.string() }),
      result: z.object({ token: z.string(), full: z.string() }),
      async *streamRun() {
        let full = '';
        for (const token of ['Hello', ' ', 'World']) {
          full += token;
          yield { token, full };
        }
      },
      update: ({ result, state }) => state.update({ response: result.full }),
    });

    expect(sa).toBeInstanceOf(StreamingAction);
    expect(sa.streaming).toBe(true);
    expect(sa.reads).toEqual(['prompt']);
    expect(sa.writes).toEqual(['response']);
  });

  test('isStreamingAction type guard', () => {
    const sa = streamingAction({
      result: z.object({ x: z.number() }),
      async *streamRun() { yield { x: 1 }; },
      update: ({ state }) => state,
    });

    const regular = action({
      update: ({ state }) => state,
    });

    expect(isStreamingAction(sa)).toBe(true);
    expect(isStreamingAction(regular)).toBe(false);
  });

  test('run() consumes generator and returns final result', async () => {
    const sa = streamingAction({
      reads: z.object({ input: z.string() }),
      writes: z.object({}),
      result: z.object({ value: z.string() }),
      async *streamRun() {
        yield { value: 'partial' };
        yield { value: 'final' };
      },
      // @ts-expect-error - empty writes
      update: ({ state }) => state,
    });

    const state = createState(z.object({ input: z.string() }), { input: 'test' });
    const result = await sa.run({ state: state as any, inputs: undefined });
    expect(result.value).toBe('final');
  });

  test('withName creates a named copy', () => {
    const sa = streamingAction({
      result: z.object({ x: z.number() }),
      async *streamRun() { yield { x: 1 }; },
      update: ({ state }) => state,
    });

    const named = sa.withName('myStream');
    expect(named.name).toBe('myStream');
    expect(sa.name).toBeUndefined();
  });
});

// ============================================================================
// StreamingResultContainer Unit Tests
// ============================================================================

describe('StreamingResultContainer', () => {
  test('iterates over intermediate results', async () => {
    async function* gen(): AsyncGenerator<{ n: number }, void, undefined> {
      yield { n: 1 };
      yield { n: 2 };
      yield { n: 3 };
    }

    const state = createState(z.object({}), {});
    const container = new StreamingResultContainer(
      gen(),
      state as any,
      (_result, state) => state,
    );

    const results: number[] = [];
    for await (const item of container) {
      results.push(item.n);
    }

    expect(results).toEqual([1, 2, 3]);
  });

  test('.get() returns final result and state', async () => {
    async function* gen(): AsyncGenerator<{ n: number }, void, undefined> {
      yield { n: 1 };
      yield { n: 2 };
    }

    const state = createState(z.object({ total: z.number() }), { total: 0 });
    const container = new StreamingResultContainer(
      gen(),
      state as any,
      (result, state) => state.update({ total: result.n }),
    );

    const { result, state: finalState } = await container.get();
    expect(result.n).toBe(2);
    expect(finalState.total).toBe(2);
  });

  test('.get() auto-consumes if not iterated', async () => {
    async function* gen(): AsyncGenerator<{ value: string }, void, undefined> {
      yield { value: 'a' };
      yield { value: 'b' };
    }

    const state = createState(z.object({}), {});
    const container = new StreamingResultContainer(
      gen(),
      state as any,
      (_result, state) => state,
    );

    // Call .get() directly without iterating
    const { result } = await container.get();
    expect(result.value).toBe('b');
  });

  test('passThrough wraps a non-streaming result', async () => {
    const state = createState(z.object({ x: z.number() }), { x: 42 });
    const container = StreamingResultContainer.passThrough(
      { value: 'done' },
      state as any
    );

    const results: string[] = [];
    for await (const item of container) {
      results.push(item.value);
    }

    expect(results).toEqual(['done']);
    const { result, state: finalState } = await container.get();
    expect(result.value).toBe('done');
    expect(finalState.x).toBe(42);
  });
});

// ============================================================================
// Application.streamStep() Integration
// ============================================================================

describe('Application.streamStep()', () => {
  test('streaming action yields intermediate results via streamStep', async () => {
    const streamCounter = streamingAction({
      reads: z.object({ count: z.number() }),
      writes: z.object({ count: z.number(), tokens: z.string() }),
      result: z.object({ token: z.string(), accumulated: z.string() }),
      async *streamRun() {
        let acc = '';
        for (const t of ['a', 'b', 'c']) {
          acc += t;
          yield { token: t, accumulated: acc };
        }
      },
      update: ({ result, state }) =>
        state.update({ count: state.count + 1, tokens: result.accumulated }),
    });

    const graph = new GraphBuilder()
      .withActions({ streamCounter })
      .withTransitions(['streamCounter', 'streamCounter'])
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
      .build();

    const result = await app.streamStep();
    expect(result).not.toBeNull();

    const intermediates: string[] = [];
    for await (const item of result!.stream) {
      intermediates.push(item.token);
    }

    expect(intermediates).toEqual(['a', 'b', 'c']);

    const { result: finalResult, state } = await result!.stream.get();
    expect(finalResult.accumulated).toBe('abc');
    expect(state.count).toBe(1);
    expect(state.tokens).toBe('abc');
  });

  test('non-streaming action works with streamStep', async () => {
    const counter = action({
      reads: z.object({ count: z.number() }),
      writes: z.object({ count: z.number() }),
      update: ({ state }) => state.update({ count: state.count + 1 }),
    });

    const graph = new GraphBuilder()
      .withActions({ counter })
      .withTransitions(['counter', 'counter'])
      .build();

    const app = new ApplicationBuilder()
      .withGraph(graph)
      .withState(createState(z.object({ count: z.number() }), { count: 0 }))
      .withEntrypoint('counter')
      .build();

    const result = await app.streamStep();
    expect(result).not.toBeNull();

    // Non-streaming action: passThrough container yields the result once
    const { state } = await result!.stream.get();
    expect(state.count).toBe(1);
  });

  test('streamStep returns null at terminal state', async () => {
    const terminal = action({
      reads: z.object({ count: z.number() }),
      writes: z.object({ count: z.number() }),
      update: ({ state }) => state.update({ count: state.count + 1 }),
    });

    const graph = new GraphBuilder()
      .withActions({ terminal })
      .withTransitions(['terminal', null])
      .build();

    const app = new ApplicationBuilder()
      .withGraph(graph)
      .withState(createState(z.object({ count: z.number() }), { count: 0 }))
      .withEntrypoint('terminal')
      .build();

    // First streamStep executes
    const first = await app.streamStep();
    expect(first).not.toBeNull();
    await first!.stream.get();

    // Second streamStep: terminal
    const second = await app.streamStep();
    expect(second).toBeNull();
  });
});
