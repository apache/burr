/**
 * Licensed to the Apache Software Foundation (ASF) under one
 * or more contributor license agreements.  See the NOTICE file
 * distributed with this work for additional information
 * regarding copyright ownership.  The ASF licenses this file
 * to you under the Apache License, Version 2.0 (the
 * "License"); you may not use this file except in compliance
 * with the License.  You may obtain a copy of the License at
 *
 *   http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing,
 * software distributed under the License is distributed on an
 * "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
 * KIND, either express or implied.  See the License for the
 * specific language governing permissions and limitations
 * under the License.
 */

// Tracking & observability: ActionSpan hierarchy, TracerFactory, and span lifecycle.
//
// Mirrors Python's burr/visibility/tracing.py.
// Uses AsyncLocalStorage for execution context (Node >= 18 guaranteed).

import { AsyncLocalStorage } from 'node:async_hooks';
import {
  type PreStartSpanHook,
  type PostEndSpanHook,
  type DoLogAttributeHook,
  type LifecycleAdapter,
} from './lifecycle';

// Re-export for convenience (these are the canonical definitions from lifecycle.ts)
export type { PreStartSpanHook, PostEndSpanHook, DoLogAttributeHook };

// ============================================================================
// ActionSpan
// ============================================================================

let _spanIdCounter = 0;

/**
 * Represents a span in the action execution tree.
 * Mirrors Python's ActionSpan.
 */
export class ActionSpan {
  readonly action: string;
  readonly actionSequenceId: number;
  readonly name: string;
  readonly parent: ActionSpan | null;
  readonly uid: string;
  readonly sequenceId: number;
  private _childCount = 0;

  constructor(
    action: string,
    actionSequenceId: number,
    name: string,
    parent: ActionSpan | null = null,
    sequenceId?: number
  ) {
    this.action = action;
    this.actionSequenceId = actionSequenceId;
    this.name = name;
    this.parent = parent;
    this.sequenceId = sequenceId ?? _spanIdCounter++;
    this.uid = `${action}:${actionSequenceId}:${this.name}:${this.sequenceId}`;
  }

  get childCount(): number {
    return this._childCount;
  }

  /**
   * Create a child span.
   */
  spawn(name: string): ActionSpan {
    this._childCount++;
    return new ActionSpan(
      this.action,
      this.actionSequenceId,
      name,
      this
    );
  }
}

// ============================================================================
// ActionSpanTracer
// ============================================================================

/**
 * Manages a single span's lifecycle: start, log attributes, end.
 */
export class ActionSpanTracer {
  readonly span: ActionSpan;
  private readonly _hooks: LifecycleAdapter[];
  private readonly _appId: string;
  private readonly _partitionKey: string | undefined;
  private readonly _dependencies: string[];
  private _started = false;
  private _ended = false;

  constructor(
    span: ActionSpan,
    hooks: LifecycleAdapter[],
    appId: string,
    partitionKey: string | undefined,
    dependencies: string[] = []
  ) {
    this.span = span;
    this._hooks = hooks;
    this._appId = appId;
    this._partitionKey = partitionKey;
    this._dependencies = dependencies;
  }

  async start(): Promise<void> {
    if (this._started) return;
    this._started = true;

    for (const hook of this._hooks) {
      if ('preStartSpan' in hook && typeof hook.preStartSpan === 'function') {
        await hook.preStartSpan({
          action: this.span.action,
          actionSequenceId: this.span.actionSequenceId,
          span: this.span,
          spanDependencies: this._dependencies,
          appId: this._appId,
          partitionKey: this._partitionKey,
        });
      }
    }
  }

  async logAttributes(attributes: Record<string, any>): Promise<void> {
    for (const hook of this._hooks) {
      if ('doLogAttributes' in hook && typeof hook.doLogAttributes === 'function') {
        await hook.doLogAttributes({
          attributes,
          action: this.span.action,
          actionSequenceId: this.span.actionSequenceId,
          span: this.span,
          appId: this._appId,
          partitionKey: this._partitionKey,
        });
      }
    }
  }

  async end(): Promise<void> {
    if (this._ended) return;
    this._ended = true;

    for (const hook of this._hooks) {
      if ('postEndSpan' in hook && typeof hook.postEndSpan === 'function') {
        await hook.postEndSpan({
          action: this.span.action,
          actionSequenceId: this.span.actionSequenceId,
          span: this.span,
          spanDependencies: this._dependencies,
          appId: this._appId,
          partitionKey: this._partitionKey,
        });
      }
    }
  }
}

// ============================================================================
// TracerFactory
// ============================================================================

/**
 * Creates span tracers for an action's execution context.
 * Injected into actions that request tracing.
 *
 * Mirrors Python's TracerFactory.
 */
export class TracerFactory {
  private readonly _appId: string;
  private readonly _partitionKey: string | undefined;
  private readonly _hooks: LifecycleAdapter[];
  private readonly _rootSpan: ActionSpan;

  constructor(
    action: string,
    actionSequenceId: number,
    appId: string,
    partitionKey: string | undefined,
    hooks: LifecycleAdapter[] = []
  ) {
    this._appId = appId;
    this._partitionKey = partitionKey;
    this._hooks = hooks;
    this._rootSpan = new ActionSpan(action, actionSequenceId, action);
  }

  get rootSpan(): ActionSpan {
    return this._rootSpan;
  }

  /**
   * Create a span tracer for a named sub-operation.
   */
  createSpan(name: string, dependencies: string[] = []): ActionSpanTracer {
    const span = this._rootSpan.spawn(name);
    return new ActionSpanTracer(
      span,
      this._hooks,
      this._appId,
      this._partitionKey,
      dependencies
    );
  }
}

// ============================================================================
// AsyncLocalStorage context for nested tracing
// ============================================================================

const tracerStorage = new AsyncLocalStorage<TracerFactory>();

/**
 * Get the current TracerFactory from the async context.
 * Returns undefined if not within a traced execution.
 */
export function getCurrentTracer(): TracerFactory | undefined {
  return tracerStorage.getStore();
}

/**
 * Run a function within a tracer context.
 * Useful for Application to inject the tracer during action execution.
 */
export function runWithTracer<T>(tracer: TracerFactory, fn: () => T): T {
  return tracerStorage.run(tracer, fn);
}

// ============================================================================
// trace() wrapper
// ============================================================================

/**
 * Wraps an async function in a span.
 * Equivalent of Python's @trace decorator.
 *
 * @example
 * ```typescript
 * const tracedFetch = trace(async (url: string) => {
 *   return fetch(url).then(r => r.json());
 * }, { spanName: 'fetch_data' });
 * ```
 */
export function trace<TArgs extends any[], TReturn>(
  fn: (...args: TArgs) => Promise<TReturn>,
  options?: {
    spanName?: string;
    captureInputs?: boolean;
    captureOutputs?: boolean;
  }
): (...args: TArgs) => Promise<TReturn> {
  const spanName = options?.spanName ?? (fn.name || 'anonymous');

  return async (...args: TArgs): Promise<TReturn> => {
    const tracer = getCurrentTracer();
    if (!tracer) {
      // No tracer in context, just run the function
      return fn(...args);
    }

    const spanTracer = tracer.createSpan(spanName);
    await spanTracer.start();

    if (options?.captureInputs) {
      await spanTracer.logAttributes({ inputs: args });
    }

    try {
      const result = await fn(...args);

      if (options?.captureOutputs) {
        await spanTracer.logAttributes({ output: result });
      }

      return result;
    } finally {
      await spanTracer.end();
    }
  };
}
