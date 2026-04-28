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

// Streaming actions and result containers
//
// Mirrors Python's StreamingAction/SingleStepStreamingAction/StreamingResultContainer.
// Uses AsyncGenerator (not ReadableStream) to match the Python generator pattern.

import { z } from 'zod';
import { StateInstance } from './state';

// ============================================================================
// StreamingAction
// ============================================================================

/**
 * A streaming action yields intermediate results, then produces a final result.
 *
 * Two-phase design (matching Python's StreamingAction):
 * - streamRun: async generator that yields intermediate results, final yield is the complete result
 * - update: transforms the final result into state writes (same as regular Action)
 *
 * The streaming protocol:
 * - Each yield produces an intermediate result dict
 * - The last yielded value is the final/complete result
 * - After the generator completes, update() is called with the final result
 */
export class StreamingAction<
  TReadsSchema extends z.ZodObject<any>,
  TWritesSchema extends z.ZodObject<any>,
  TInputsSchema extends z.ZodType,
  TResultSchema extends z.ZodObject<any>
> {
  private readonly _name?: string;
  private readonly _reads: TReadsSchema;
  private readonly _writes: TWritesSchema;
  private readonly _inputs: TInputsSchema;
  private readonly _result: TResultSchema;

  private readonly _streamRunFn: (params: {
    state: StateInstance<TReadsSchema, TReadsSchema, TWritesSchema>;
    inputs: z.infer<TInputsSchema>;
  }) => AsyncGenerator<z.infer<TResultSchema>, void, undefined>;

  private readonly _updateFn: (params: {
    result: z.infer<TResultSchema>;
    state: StateInstance<TReadsSchema, TReadsSchema, TWritesSchema>;
    inputs: z.infer<TInputsSchema>;
  }) => StateInstance<z.ZodType<z.infer<TWritesSchema>>, any, z.ZodType<z.infer<TWritesSchema>>>;

  private readonly _readsKeys: readonly string[];
  private readonly _writesKeys: readonly string[];
  private readonly _inputsKeys: readonly string[];

  constructor(config: {
    name?: string;
    reads: TReadsSchema;
    writes: TWritesSchema;
    inputs: TInputsSchema;
    result: TResultSchema;
    streamRun: (params: {
      state: StateInstance<TReadsSchema, TReadsSchema, TWritesSchema>;
      inputs: z.infer<TInputsSchema>;
    }) => AsyncGenerator<z.infer<TResultSchema>, void, undefined>;
    update: (params: {
      result: z.infer<TResultSchema>;
      state: StateInstance<TReadsSchema, TReadsSchema, TWritesSchema>;
      inputs: z.infer<TInputsSchema>;
    }) => StateInstance<z.ZodType<z.infer<TWritesSchema>>, any, z.ZodType<z.infer<TWritesSchema>>>;
  }) {
    this._name = config.name;
    this._reads = config.reads;
    this._writes = config.writes;
    this._inputs = config.inputs;
    this._result = config.result;
    this._streamRunFn = config.streamRun;
    this._updateFn = config.update;

    this._readsKeys = this.extractKeys(config.reads);
    this._writesKeys = this.extractKeys(config.writes);
    this._inputsKeys = this.extractKeys(config.inputs);
  }

  private extractKeys(schema: z.ZodType): readonly string[] {
    if (schema instanceof z.ZodObject) {
      return Object.keys(schema.shape);
    }
    return [];
  }

  get name(): string | undefined { return this._name; }
  get reads(): readonly string[] { return this._readsKeys; }
  get writes(): readonly string[] { return this._writesKeys; }
  get inputs(): readonly string[] { return this._inputsKeys; }
  get streaming(): boolean { return true; }

  get schema() {
    return {
      reads: this._reads,
      writes: this._writes,
      inputs: this._inputs,
      result: this._result,
    } as const;
  }

  withName(name: string): StreamingAction<TReadsSchema, TWritesSchema, TInputsSchema, TResultSchema> {
    return new StreamingAction({
      name,
      reads: this._reads,
      writes: this._writes,
      inputs: this._inputs,
      result: this._result,
      streamRun: this._streamRunFn,
      update: this._updateFn,
    });
  }

  /**
   * Returns the async generator that yields intermediate results.
   * The last yielded value is the final result.
   */
  streamRun(params: {
    state: StateInstance<TReadsSchema, TReadsSchema, TWritesSchema>;
    inputs: z.infer<TInputsSchema>;
  }): AsyncGenerator<z.infer<TResultSchema>, void, undefined> {
    return this._streamRunFn(params);
  }

  /**
   * Transform the final result into state writes.
   */
  update(params: {
    result: z.infer<TResultSchema>;
    state: StateInstance<TReadsSchema, TReadsSchema, TWritesSchema>;
    inputs: z.infer<TInputsSchema>;
  }): StateInstance<z.ZodType<z.infer<TWritesSchema>>, any, z.ZodType<z.infer<TWritesSchema>>> {
    return this._updateFn(params);
  }

  /**
   * Non-streaming execution: runs the generator to completion and returns
   * the final result. This allows a StreamingAction to be used where a
   * regular Action is expected.
   */
  async run(params: {
    state: StateInstance<TReadsSchema, TReadsSchema, TWritesSchema>;
    inputs: z.infer<TInputsSchema>;
  }): Promise<z.infer<TResultSchema>> {
    const gen = this.streamRun(params);
    let lastResult: z.infer<TResultSchema> | undefined;
    for await (const item of gen) {
      lastResult = item;
    }
    return lastResult!;
  }
}

// ============================================================================
// Factory Function
// ============================================================================

/**
 * Creates a streaming action.
 *
 * @example
 * ```typescript
 * const streamChat = streamingAction({
 *   reads: z.object({ prompt: z.string() }),
 *   writes: z.object({ response: z.string() }),
 *   inputs: z.void(),
 *   result: z.object({ token: z.string(), full: z.string() }),
 *
 *   async *streamRun({ state }) {
 *     let full = '';
 *     for await (const token of llmStream(state.prompt)) {
 *       full += token;
 *       yield { token, full };
 *     }
 *     // Last yield is the final result
 *   },
 *
 *   update: ({ result, state }) => state.update({ response: result.full }),
 * });
 * ```
 */
export function streamingAction<
  TReadsSchema extends z.ZodObject<any> = z.ZodObject<{}>,
  TWritesSchema extends z.ZodObject<any> = z.ZodObject<{}>,
  TInputsSchema extends z.ZodType = z.ZodVoid,
  TResultSchema extends z.ZodObject<any> = z.ZodObject<{}>
>(config: {
  reads?: TReadsSchema;
  writes?: TWritesSchema;
  inputs?: TInputsSchema;
  result: TResultSchema;
  streamRun: (params: {
    state: StateInstance<TReadsSchema, TReadsSchema, TWritesSchema>;
    inputs: z.infer<TInputsSchema>;
  }) => AsyncGenerator<z.infer<TResultSchema>, void, undefined>;
  update: (params: {
    result: z.infer<TResultSchema>;
    state: StateInstance<TReadsSchema, TReadsSchema, TWritesSchema>;
    inputs: z.infer<TInputsSchema>;
  }) => StateInstance<z.ZodType<z.infer<TWritesSchema>>, any, z.ZodType<z.infer<TWritesSchema>>>;
}): StreamingAction<TReadsSchema, TWritesSchema, TInputsSchema, TResultSchema> {
  const reads = (config.reads ?? z.object({})) as TReadsSchema;
  const writes = (config.writes ?? z.object({})) as TWritesSchema;
  const inputs = (config.inputs ?? z.void()) as TInputsSchema;

  return new StreamingAction({
    reads,
    writes,
    inputs,
    result: config.result,
    streamRun: config.streamRun,
    update: config.update,
  });
}

// ============================================================================
// StreamingResultContainer
// ============================================================================

/**
 * Container for consuming a streaming action's results.
 *
 * Mirrors Python's StreamingResultContainer:
 * 1. Iterate over intermediate results as they come in
 * 2. Get the final result + state after iteration completes
 *
 * @example
 * ```typescript
 * const container = new StreamingResultContainer(generator, state, updateFn);
 * for await (const intermediate of container) {
 *   console.log(intermediate.token);
 * }
 * const { result, state } = await container.get();
 * ```
 */
export class StreamingResultContainer<TResult = Record<string, any>> {
  private readonly _generator: AsyncGenerator<TResult, void, undefined>;
  private readonly _forkedState: StateInstance<any, any, any>;
  private readonly _updateFn: (result: TResult, state: StateInstance<any, any, any>) => StateInstance<any, any, any>;
  private _finalResult: TResult | undefined;
  private _finalState: StateInstance<any, any, any> | undefined;
  private _done = false;

  /**
   * Create a pass-through container for non-streaming actions.
   * Wraps a completed result in the streaming API for uniform consumption.
   */
  static passThrough<T>(
    result: T,
    finalState: StateInstance<any, any, any>
  ): StreamingResultContainer<T> {
    async function* singleYield(): AsyncGenerator<T, void, undefined> {
      yield result;
    }
    const container = new StreamingResultContainer<T>(
      singleYield(),
      finalState,
      () => finalState,
    );
    return container;
  }

  constructor(
    generator: AsyncGenerator<TResult, void, undefined>,
    forkedState: StateInstance<any, any, any>,
    updateFn: (result: TResult, state: StateInstance<any, any, any>) => StateInstance<any, any, any>,
  ) {
    this._generator = generator;
    this._forkedState = forkedState;
    this._updateFn = updateFn;
  }

  /**
   * Iterate over intermediate results.
   * The last value yielded by the generator becomes the final result.
   */
  async *[Symbol.asyncIterator](): AsyncGenerator<TResult, void, undefined> {
    let lastResult: TResult | undefined;
    for await (const item of this._generator) {
      lastResult = item;
      yield item;
    }
    this._finalResult = lastResult;
    this._finalState = lastResult !== undefined
      ? this._updateFn(lastResult, this._forkedState)
      : this._forkedState;
    this._done = true;
  }

  /**
   * Get the final result and state.
   * If the iterator hasn't been fully consumed, consumes it first.
   */
  async get(): Promise<{ result: TResult; state: StateInstance<any, any, any> }> {
    if (!this._done) {
      // Consume the generator
      // eslint-disable-next-line @typescript-eslint/no-unused-vars
      for await (const _item of this) {
        // consume
      }
    }
    return {
      result: this._finalResult!,
      state: this._finalState!,
    };
  }
}

// ============================================================================
// Type guard
// ============================================================================

/**
 * Check if an action is a streaming action.
 */
export function isStreamingAction(action: any): action is StreamingAction<any, any, any, any> {
  return action instanceof StreamingAction;
}
