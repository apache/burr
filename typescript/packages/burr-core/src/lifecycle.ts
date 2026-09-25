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

// Lifecycle hooks for application and action execution
//
// Mirrors Python's burr/lifecycle/base.py but async-only (all TS execution is async).
// Python has sync + async variants for each hook; we collapse to a single async interface.

import { StateInstance } from './state';
import { Graph } from './graph';
import { type ActionLike } from './types';
import { type ActionSpan } from './tracing';

// ============================================================================
// Enums
// ============================================================================

/**
 * Which application method the user called.
 * Mirrors Python's ExecuteMethod enum.
 */
export type ExecuteMethod =
  | 'step'
  | 'run'
  | 'iterate'
  | 'streamStep';

// ============================================================================
// Hook Parameter Types
// ============================================================================

/** Mirrors Python's PreRunStepHook.pre_run_step signature. */
export interface PreRunStepParams {
  appId: string;
  partitionKey: string | undefined;
  sequenceId: number;
  state: StateInstance<any, any, any>;
  action: ActionLike<any, any, any, any>;
  inputs: Record<string, any>;
}

/** Mirrors Python's PostRunStepHook.post_run_step signature. */
export interface PostRunStepParams {
  appId: string;
  partitionKey: string | undefined;
  sequenceId: number;
  state: StateInstance<any, any, any>;
  action: ActionLike<any, any, any, any>;
  result: Record<string, any> | void | null;
  exception: Error | null;
}

/** Mirrors Python's PostApplicationCreateHook.post_application_create signature. */
export interface PostApplicationCreateParams {
  appId: string;
  partitionKey: string | undefined;
  state: StateInstance<any, any, any>;
  graph: Graph<any>;
  entrypoint: string;
  parentPointer?: { appId: string; sequenceId: number; partitionKey?: string } | null;
  spawningParentPointer?: { appId: string; sequenceId: number; partitionKey?: string } | null;
}

/** Mirrors Python's PreStartSpanHook params. */
export interface PreStartSpanParams {
  action: string;
  actionSequenceId: number;
  span: ActionSpan;
  spanDependencies: string[];
  appId: string;
  partitionKey: string | undefined;
}

/** Mirrors Python's PostEndSpanHook params. */
export interface PostEndSpanParams {
  action: string;
  actionSequenceId: number;
  span: ActionSpan;
  spanDependencies: string[];
  appId: string;
  partitionKey: string | undefined;
}

/** Mirrors Python's DoLogAttributeHook params. */
export interface DoLogAttributeParams {
  attributes: Record<string, any>;
  action: string;
  actionSequenceId: number;
  span: ActionSpan | null;
  appId: string;
  partitionKey: string | undefined;
}

/** Mirrors Python's PreApplicationExecuteCallHook params. */
export interface PreExecuteCallParams {
  appId: string;
  partitionKey: string | undefined;
  state: StateInstance<any, any, any>;
  method: ExecuteMethod;
}

/** Mirrors Python's PostApplicationExecuteCallHook params. */
export interface PostExecuteCallParams {
  appId: string;
  partitionKey: string | undefined;
  state: StateInstance<any, any, any>;
  method: ExecuteMethod;
  exception: Error | null;
}

/** Mirrors Python's PreStartStreamHook params. */
export interface PreStartStreamParams {
  action: string;
  sequenceId: number;
  appId: string;
  partitionKey: string | undefined;
}

/** Mirrors Python's PostStreamItemHook params. */
export interface PostStreamItemParams {
  item: any;
  itemIndex: number;
  streamInitializeTime: Date;
  firstStreamItemStartTime: Date;
  action: string;
  sequenceId: number;
  appId: string;
  partitionKey: string | undefined;
}

/** Mirrors Python's PostEndStreamHook params. */
export interface PostEndStreamParams {
  action: string;
  sequenceId: number;
  appId: string;
  partitionKey: string | undefined;
}

// ============================================================================
// Hook Interfaces (all 11 types from Python, async-only)
// ============================================================================

/** Hook that runs before a step is executed. */
export interface PreRunStepHook {
  preRunStep(params: PreRunStepParams): Promise<void>;
}

/** Hook that runs after a step is executed (including on failure). */
export interface PostRunStepHook {
  postRunStep(params: PostRunStepParams): Promise<void>;
}

/** Hook that runs after an Application is constructed (after build()). */
export interface PostApplicationCreateHook {
  postApplicationCreate(params: PostApplicationCreateParams): Promise<void>;
}

/** Hook that runs before a span starts. */
export interface PreStartSpanHook {
  preStartSpan(params: PreStartSpanParams): Promise<void>;
}

/** Hook that runs after a span ends. */
export interface PostEndSpanHook {
  postEndSpan(params: PostEndSpanParams): Promise<void>;
}

/** Hook for logging attributes during a span. */
export interface DoLogAttributeHook {
  doLogAttributes(params: DoLogAttributeParams): Promise<void>;
}

/** Hook that runs before an application execute method (step/run/iterate/streamStep) is called. */
export interface PreExecuteCallHook {
  preExecuteCall(params: PreExecuteCallParams): Promise<void>;
}

/** Hook that runs after an application execute method completes. */
export interface PostExecuteCallHook {
  postExecuteCall(params: PostExecuteCallParams): Promise<void>;
}

/** Hook that runs when a stream starts. */
export interface PreStartStreamHook {
  preStartStream(params: PreStartStreamParams): Promise<void>;
}

/** Hook that runs after each streamed item is yielded. */
export interface PostStreamItemHook {
  postStreamItem(params: PostStreamItemParams): Promise<void>;
}

/** Hook that runs after a stream ends. */
export interface PostEndStreamHook {
  postEndStream(params: PostEndStreamParams): Promise<void>;
}

// ============================================================================
// LifecycleAdapter
// ============================================================================

/**
 * Union of all hook interfaces.
 * A lifecycle adapter can implement any subset of hooks.
 * Adapters are duck-typed by checking for method existence.
 */
export type LifecycleAdapter = Partial<
  PreRunStepHook &
  PostRunStepHook &
  PostApplicationCreateHook &
  PreStartSpanHook &
  PostEndSpanHook &
  DoLogAttributeHook &
  PreExecuteCallHook &
  PostExecuteCallHook &
  PreStartStreamHook &
  PostStreamItemHook &
  PostEndStreamHook
>;

// ============================================================================
// Hook Type Guards
// ============================================================================

export function isPreRunStepHook(adapter: LifecycleAdapter): adapter is PreRunStepHook {
  return typeof (adapter as any).preRunStep === 'function';
}
export function isPostRunStepHook(adapter: LifecycleAdapter): adapter is PostRunStepHook {
  return typeof (adapter as any).postRunStep === 'function';
}
export function isPostApplicationCreateHook(adapter: LifecycleAdapter): adapter is PostApplicationCreateHook {
  return typeof (adapter as any).postApplicationCreate === 'function';
}
export function isPreStartSpanHook(adapter: LifecycleAdapter): adapter is PreStartSpanHook {
  return typeof (adapter as any).preStartSpan === 'function';
}
export function isPostEndSpanHook(adapter: LifecycleAdapter): adapter is PostEndSpanHook {
  return typeof (adapter as any).postEndSpan === 'function';
}
export function isDoLogAttributeHook(adapter: LifecycleAdapter): adapter is DoLogAttributeHook {
  return typeof (adapter as any).doLogAttributes === 'function';
}
export function isPreExecuteCallHook(adapter: LifecycleAdapter): adapter is PreExecuteCallHook {
  return typeof (adapter as any).preExecuteCall === 'function';
}
export function isPostExecuteCallHook(adapter: LifecycleAdapter): adapter is PostExecuteCallHook {
  return typeof (adapter as any).postExecuteCall === 'function';
}
export function isPreStartStreamHook(adapter: LifecycleAdapter): adapter is PreStartStreamHook {
  return typeof (adapter as any).preStartStream === 'function';
}
export function isPostStreamItemHook(adapter: LifecycleAdapter): adapter is PostStreamItemHook {
  return typeof (adapter as any).postStreamItem === 'function';
}
export function isPostEndStreamHook(adapter: LifecycleAdapter): adapter is PostEndStreamHook {
  return typeof (adapter as any).postEndStream === 'function';
}

// ============================================================================
// LifecycleAdapterSet
// ============================================================================

/**
 * Generic hook dispatcher. Calls all adapters that implement a given hook,
 * collecting errors without stopping dispatch.
 */
async function dispatchHook<TParams>(
  adapters: readonly LifecycleAdapter[],
  hookName: string,
  guard: (adapter: LifecycleAdapter) => boolean,
  params: TParams
): Promise<void> {
  const errors: Error[] = [];
  for (const adapter of adapters) {
    if (guard(adapter)) {
      try {
        await (adapter as any)[hookName](params);
      } catch (e) {
        errors.push(e instanceof Error ? e : new Error(String(e)));
      }
    }
  }
  if (errors.length > 0) {
    throw new AggregateError(errors, `${errors.length} ${hookName} hook(s) failed`);
  }
}

/**
 * Dispatches hook calls to all registered adapters that implement the hook.
 *
 * Mirrors Python's LifecycleAdapterSet (burr/lifecycle/internal.py).
 * Uses a generic dispatch pattern so new hook types don't require new methods.
 */
export class LifecycleAdapterSet {
  private readonly _adapters: readonly LifecycleAdapter[];

  constructor(adapters: LifecycleAdapter[] = []) {
    this._adapters = Object.freeze([...adapters]);
  }

  get adapters(): readonly LifecycleAdapter[] {
    return this._adapters;
  }

  // Step hooks
  async callPreRunStep(params: PreRunStepParams): Promise<void> {
    await dispatchHook(this._adapters, 'preRunStep', isPreRunStepHook, params);
  }
  async callPostRunStep(params: PostRunStepParams): Promise<void> {
    await dispatchHook(this._adapters, 'postRunStep', isPostRunStepHook, params);
  }

  // Application create hook
  async callPostApplicationCreate(params: PostApplicationCreateParams): Promise<void> {
    await dispatchHook(this._adapters, 'postApplicationCreate', isPostApplicationCreateHook, params);
  }

  // Span hooks
  async callPreStartSpan(params: PreStartSpanParams): Promise<void> {
    await dispatchHook(this._adapters, 'preStartSpan', isPreStartSpanHook, params);
  }
  async callPostEndSpan(params: PostEndSpanParams): Promise<void> {
    await dispatchHook(this._adapters, 'postEndSpan', isPostEndSpanHook, params);
  }
  async callDoLogAttributes(params: DoLogAttributeParams): Promise<void> {
    await dispatchHook(this._adapters, 'doLogAttributes', isDoLogAttributeHook, params);
  }

  // Execute call hooks
  async callPreExecuteCall(params: PreExecuteCallParams): Promise<void> {
    await dispatchHook(this._adapters, 'preExecuteCall', isPreExecuteCallHook, params);
  }
  async callPostExecuteCall(params: PostExecuteCallParams): Promise<void> {
    await dispatchHook(this._adapters, 'postExecuteCall', isPostExecuteCallHook, params);
  }

  // Stream hooks
  async callPreStartStream(params: PreStartStreamParams): Promise<void> {
    await dispatchHook(this._adapters, 'preStartStream', isPreStartStreamHook, params);
  }
  async callPostStreamItem(params: PostStreamItemParams): Promise<void> {
    await dispatchHook(this._adapters, 'postStreamItem', isPostStreamItemHook, params);
  }
  async callPostEndStream(params: PostEndStreamParams): Promise<void> {
    await dispatchHook(this._adapters, 'postEndStream', isPostEndStreamHook, params);
  }
}
