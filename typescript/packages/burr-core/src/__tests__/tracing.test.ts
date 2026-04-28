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

import {
  ActionSpan,
  TracerFactory,
  ActionSpanTracer,
  getCurrentTracer,
  runWithTracer,
  trace,
  type PreStartSpanHook,
  type PostEndSpanHook,
  type DoLogAttributeHook,
} from '../tracing';

// ============================================================================
// ActionSpan
// ============================================================================

describe('ActionSpan', () => {
  test('creates span with uid', () => {
    const span = new ActionSpan('myAction', 1, 'root');
    expect(span.action).toBe('myAction');
    expect(span.actionSequenceId).toBe(1);
    expect(span.name).toBe('root');
    expect(span.parent).toBeNull();
    expect(span.uid).toContain('myAction:1:root');
  });

  test('spawn creates child span', () => {
    const root = new ActionSpan('act', 1, 'root');
    const child = root.spawn('child1');

    expect(child.parent).toBe(root);
    expect(child.name).toBe('child1');
    expect(child.action).toBe('act');
    expect(root.childCount).toBe(1);
  });

  test('spawn multiple children increments childCount', () => {
    const root = new ActionSpan('act', 1, 'root');
    root.spawn('c1');
    root.spawn('c2');
    root.spawn('c3');
    expect(root.childCount).toBe(3);
  });
});

// ============================================================================
// TracerFactory
// ============================================================================

describe('TracerFactory', () => {
  test('creates span tracers with root span as parent', () => {
    const factory = new TracerFactory('myAction', 5, 'app1', 'pk');
    const tracer = factory.createSpan('sub_operation');

    expect(tracer.span.name).toBe('sub_operation');
    expect(tracer.span.parent).toBe(factory.rootSpan);
  });

  test('createSpan increments root child count', () => {
    const factory = new TracerFactory('act', 1, 'app1', undefined);
    factory.createSpan('s1');
    factory.createSpan('s2');
    expect(factory.rootSpan.childCount).toBe(2);
  });
});

// ============================================================================
// ActionSpanTracer with hooks
// ============================================================================

describe('ActionSpanTracer', () => {
  test('calls preStartSpan hook on start()', async () => {
    const started: string[] = [];
    const hook: PreStartSpanHook = {
      async preStartSpan({ span }) { started.push(span.name); },
    };

    const span = new ActionSpan('act', 1, 'test_span');
    const tracer = new ActionSpanTracer(span, [hook], 'app1', undefined);

    await tracer.start();
    expect(started).toEqual(['test_span']);
  });

  test('calls postEndSpan hook on end()', async () => {
    const ended: string[] = [];
    const hook: PostEndSpanHook = {
      async postEndSpan({ span }) { ended.push(span.name); },
    };

    const span = new ActionSpan('act', 1, 'test_span');
    const tracer = new ActionSpanTracer(span, [hook], 'app1', undefined);

    await tracer.start();
    await tracer.end();
    expect(ended).toEqual(['test_span']);
  });

  test('calls doLogAttributes hook', async () => {
    const logged: Record<string, any>[] = [];
    const hook: DoLogAttributeHook = {
      async doLogAttributes({ attributes }) { logged.push(attributes); },
    };

    const span = new ActionSpan('act', 1, 'test_span');
    const tracer = new ActionSpanTracer(span, [hook], 'app1', undefined);

    await tracer.logAttributes({ key: 'value' });
    expect(logged).toEqual([{ key: 'value' }]);
  });

  test('start and end are idempotent', async () => {
    let startCount = 0;
    let endCount = 0;
    const hook: PreStartSpanHook & PostEndSpanHook = {
      async preStartSpan() { startCount++; },
      async postEndSpan() { endCount++; },
    };

    const span = new ActionSpan('act', 1, 'test_span');
    const tracer = new ActionSpanTracer(span, [hook], 'app1', undefined);

    await tracer.start();
    await tracer.start(); // second call should be no-op
    await tracer.end();
    await tracer.end(); // second call should be no-op

    expect(startCount).toBe(1);
    expect(endCount).toBe(1);
  });
});

// ============================================================================
// AsyncLocalStorage context
// ============================================================================

describe('Tracer context (AsyncLocalStorage)', () => {
  test('getCurrentTracer returns undefined outside context', () => {
    expect(getCurrentTracer()).toBeUndefined();
  });

  test('runWithTracer sets tracer in context', () => {
    const factory = new TracerFactory('act', 1, 'app1', undefined);

    runWithTracer(factory, () => {
      const current = getCurrentTracer();
      expect(current).toBe(factory);
    });

    // Outside context, undefined again
    expect(getCurrentTracer()).toBeUndefined();
  });

  test('nested runWithTracer scopes correctly', () => {
    const outer = new TracerFactory('outer', 1, 'app1', undefined);
    const inner = new TracerFactory('inner', 2, 'app1', undefined);

    runWithTracer(outer, () => {
      expect(getCurrentTracer()).toBe(outer);

      runWithTracer(inner, () => {
        expect(getCurrentTracer()).toBe(inner);
      });

      expect(getCurrentTracer()).toBe(outer);
    });
  });
});

// ============================================================================
// trace() wrapper
// ============================================================================

describe('trace() wrapper', () => {
  test('runs function without tracer in context', async () => {
    const fn = trace(async (x: number) => x * 2);
    const result = await fn(5);
    expect(result).toBe(10);
  });

  test('creates span when tracer is in context', async () => {
    const started: string[] = [];
    const ended: string[] = [];
    const hooks: (PreStartSpanHook & PostEndSpanHook)[] = [{
      async preStartSpan({ span }) { started.push(span.name); },
      async postEndSpan({ span }) { ended.push(span.name); },
    }];

    const factory = new TracerFactory('act', 1, 'app1', undefined, hooks);

    const tracedFn = trace(
      async (x: number) => x + 1,
      { spanName: 'compute' }
    );

    const result = await runWithTracer(factory, () => tracedFn(10));
    expect(result).toBe(11);
    expect(started).toEqual(['compute']);
    expect(ended).toEqual(['compute']);
  });

  test('captures inputs and outputs when configured', async () => {
    const logged: Record<string, any>[] = [];
    const hooks: DoLogAttributeHook[] = [{
      async doLogAttributes({ attributes }) { logged.push(attributes); },
    }];

    const factory = new TracerFactory('act', 1, 'app1', undefined, hooks);

    const tracedFn = trace(
      async (a: number, b: number) => a + b,
      { spanName: 'add', captureInputs: true, captureOutputs: true }
    );

    await runWithTracer(factory, () => tracedFn(3, 4));
    expect(logged).toEqual([
      { inputs: [3, 4] },
      { output: 7 },
    ]);
  });

  test('ends span even on error', async () => {
    const ended: string[] = [];
    const hooks: (PreStartSpanHook & PostEndSpanHook)[] = [{
      async preStartSpan() {},
      async postEndSpan({ span }) { ended.push(span.name); },
    }];

    const factory = new TracerFactory('act', 1, 'app1', undefined, hooks);

    const tracedFn = trace(
      async () => { throw new Error('boom'); },
      { spanName: 'failing' }
    );

    await expect(
      runWithTracer(factory, () => tracedFn())
    ).rejects.toThrow('boom');

    expect(ended).toEqual(['failing']);
  });
});
