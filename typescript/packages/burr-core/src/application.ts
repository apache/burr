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

// Application runtime and execution engine

import { Graph } from './graph';
import { StateInstance, isReservedMetadataKey } from './state';
import { Action } from './action';
import { z } from 'zod';
import { LifecycleAdapterSet, type LifecycleAdapter, type ExecuteMethod } from './lifecycle';
import { isStreamingAction, StreamingResultContainer } from './streaming';
import { type ActionLike } from './types';

// ============================================================================
// Framework Metadata Schemas
// ============================================================================

/**
 * Application metadata - frozen for the lifecycle of this execution.
 * Set once at application initialization, never changes during execution.
 * 
 * Stored in state as: state.appMetadata
 */
export const AppMetadataSchema = z.object({
  /** Unique identifier for this application instance */
  appId: z.string(),
  
  /** Optional partition key for grouping/querying application runs */
  partitionKey: z.string().optional(),
  
  /** The entrypoint action name where execution starts */
  entrypoint: z.string(),
});

export type AppMetadata = z.infer<typeof AppMetadataSchema>;

/**
 * Execution metadata - changes on every step.
 * Tracks the runtime state of execution flow.
 * 
 * Stored in state as: state.executionMetadata
 */
export const ExecutionMetadataSchema = z.object({
  /** Current sequence number (increments on each step, starts at 0) */
  sequenceId: z.number(),
  
  /** 
   * Name of the last executed action.
   * Used by graph to determine next action via transitions.
   * Undefined at start (before first action is executed).
   */
  priorStep: z.string().optional(),
});

export type ExecutionMetadata = z.infer<typeof ExecutionMetadataSchema>;

/**
 * Combined framework metadata that gets merged into user state.
 * Application state will include: UserData & FrameworkMetadata
 */
export interface FrameworkMetadata {
  /** Application-level metadata (immutable during execution) */
  appMetadata: AppMetadata;
  
  /** Execution-level metadata (updates each step) */
  executionMetadata: ExecutionMetadata;
}

// ============================================================================
// Type Helpers for State with Metadata
// ============================================================================

/**
 * Application's internal state schema = user's state schema + framework metadata.
 * This is what Application works with internally.
 */
type TApplicationStateSchema<TStateSchema extends z.ZodType<Record<string, any>>> = 
  z.ZodType<z.infer<TStateSchema> & FrameworkMetadata>;

/**
 * StateInstance with framework metadata included.
 * This is the type of state that Application manages and returns to users.
 */
type ApplicationStateInstance<TStateSchema extends z.ZodType<Record<string, any>>> = 
  StateInstance<
    TApplicationStateSchema<TStateSchema>,
    TApplicationStateSchema<TStateSchema>,
    TApplicationStateSchema<TStateSchema>
  >;

// ============================================================================
// Execution Result Types
// ============================================================================

/**
 * Base execution result structure.
 * Used by both step() and run() to return consistent data.
 * 
 * @template TStateSchema - The user's state schema (without metadata)
 */
export interface ExecutionResult<TStateSchema extends z.ZodType<Record<string, any>>> {
  /** The action that was executed (null if halted before execution) */
  action: ActionLike<any, any, any, any> | null;
  
  /** The result returned from action.run() (null if halted before execution or no result) */
  result: Record<string, any> | void | null;
  
  /** 
   * The state after the action.
   * Includes user data + framework metadata (appMetadata, executionMetadata)
   */
  state: ApplicationStateInstance<TStateSchema>;
}

/**
 * Result of executing a single step.
 * Extends ExecutionResult with next action information.
 * 
 * @template TStateSchema - The user's state schema (without metadata)
 */
export interface StepResult<TStateSchema extends z.ZodType<Record<string, any>>> 
  extends ExecutionResult<TStateSchema> {
  /**
   * The action that was executed.
   * Non-null for StepResult (step() returns null instead of a result when terminal)
   */
  action: ActionLike<any, any, any, any>;
  
  /** The result returned from action.run() */
  result: Record<string, any> | void;
}

/**
 * Result of running the application to completion.
 * Same as ExecutionResult - no additional fields needed.
 * 
 * @template TStateSchema - The user's state schema (without metadata)
 */
export type RunResult<TStateSchema extends z.ZodType<Record<string, any>>> = 
  ExecutionResult<TStateSchema>;

/**
 * Options for controlling execution.
 * 
 * Matches Python's API: halt_before, halt_after, inputs.
 * Note: maxSteps, timeout, and haltCondition are TypeScript-only extensions
 * and not part of the Python API.
 */
export interface ExecutionOptions {
  /** Runtime inputs to pass to actions */
  inputs?: Record<string, any>;
  
  /** Halt before executing these actions (by name or tag like "@tag:myTag") */
  haltBefore?: string[];
  
  /** Halt after executing these actions (by name or tag like "@tag:myTag") */
  haltAfter?: string[];
}

/**
 * Represents a runnable application.
 * An application combines a graph structure with runtime configuration.
 * 
 * @template TStateSchema - The user's state schema (without framework metadata)
 */
export class Application<TStateSchema extends z.ZodType<Record<string, any>> = z.ZodType<Record<string, any>>> {
  /** The graph defining the structure of the application */
  readonly graph: Graph<TStateSchema>;
  
  /** The name of the action to start execution at */
  readonly entrypoint: string;
  
  /** Application unique identifier */
  readonly appId: string;
  
  /** Optional partition key for grouping/querying application runs */
  readonly partitionKey?: string;
  
  /** Internal runtime state (includes user data + framework metadata) */
  private _state: ApplicationStateInstance<TStateSchema>;

  /** Lifecycle hook dispatcher */
  private readonly _adapterSet: LifecycleAdapterSet;

  /** @internal Type-level field for state schema tracking (not used at runtime) */
  // @ts-expect-error - This field is only for type-level tracking, not used at runtime
  private readonly _stateSchema!: TStateSchema;

  constructor(
    graph: Graph<TStateSchema>,
    entrypoint: string,
    initialState: StateInstance<TStateSchema, TStateSchema, TStateSchema>,
    appId: string,
    partitionKey?: string,
    initialSequenceId?: number,
    lifecycleAdapters?: LifecycleAdapter[]
  ) {
    this.graph = graph;
    this.entrypoint = entrypoint;
    this.appId = appId;
    this.partitionKey = partitionKey;
    this._adapterSet = new LifecycleAdapterSet(lifecycleAdapters ?? []);
    
    // Check if state already has metadata (resumption case)
    const existingData = initialState.data as any;
    const hasExistingMetadata = existingData.executionMetadata !== undefined;
    
    // Extend user's state with framework metadata
    // Preserve existing metadata if present (for resumption), otherwise initialize
    this._state = initialState.update({
      appMetadata: hasExistingMetadata ? existingData.appMetadata : {
        appId,
        partitionKey,
        entrypoint,
      },
      executionMetadata: hasExistingMetadata ? existingData.executionMetadata : {
        sequenceId: initialSequenceId ?? 0,
        // priorStep starts undefined
      },
    } as any) as ApplicationStateInstance<TStateSchema>;
  }
  
  /**
   * Get the current state (includes metadata).
   */
  get state(): ApplicationStateInstance<TStateSchema> {
    return this._state;
  }
  
  /**
   * Get current execution metadata.
   */
  private get executionMetadata() {
    return (this._state.data).executionMetadata;
  }
  
  /**
   * Increment the sequence ID.
   */
  private incrementSequenceId(): void {
    this._state = this._state.update({
      executionMetadata: {
        ...this.executionMetadata,
        sequenceId: this.executionMetadata.sequenceId + 1,
      }
    } as any) as ApplicationStateInstance<TStateSchema>;
  }
  
  /**
   * Set the prior step (last executed action name).
   */
  private setPriorStep(actionName: string): void {
    this._state = this._state.update({
      executionMetadata: {
        ...this.executionMetadata,
        priorStep: actionName,
      }
    } as any) as ApplicationStateInstance<TStateSchema>;
  }

  /**
   * Get the next action to execute based on current state.
   * @internal
   */
  private getNextAction(): ActionLike<any, any, any, any> | null {
    const priorStep = this.executionMetadata.priorStep;
    
    // If no prior step, start at entrypoint
    if (!priorStep) {
      const action = this.graph.getAction(this.entrypoint);
      return action || null;
    }
    
    // Get transitions from the prior action
    const transitions = this.graph.getTransitionsFrom(priorStep);
    
    // Evaluate transitions in order until one matches
    for (const transition of transitions) {
      // No condition = always transition (default condition)
      const conditionMet = !transition.condition || transition.condition(this._state.data);
      
      if (conditionMet) {
        // Check if this is a terminal transition
        if (transition.to === null) {
          return null;
        }
        
        const action = this.graph.getAction(transition.to);
        return action || null;
      }
    }
    
    // No transitions found - terminal state
    return null;
  }
  
  /**
   * Core execution unit: Fork → Launch → Gather → Commit
   * 
   * Executes a single action through four distinct phases:
   * 1. FORK: Subset state to action's declared reads (copy-on-write view)
   * 2. LAUNCH: Execute action's run phase with forked state
   * 3. GATHER: Execute action's update phase to collect writes
   * 4. COMMIT: Merge writes back into committed state
   * 
   * @internal
   */
  private async runStep(
    action: ActionLike<any, any, any, any>,
    inputs: Record<string, any>
  ): Promise<{
    action: ActionLike<any, any, any, any>;
    result: Record<string, any> | void;
    newState: ApplicationStateInstance<TStateSchema>;
  }> {
    // Snapshot committed state
    const committedState = this._state;
    // Cast to Action for run/update methods (runStep is only called for non-streaming actions)
    const concreteAction = action as Action<any, any, any, any>;

    // ====================================
    // PHASE 1: FORK
    // ====================================
    // Subset state to reads (copy-on-write view)
    const forkedState = committedState.subset(action.reads) as StateInstance<any, any, any>;

    // ====================================
    // PHASE 2: LAUNCH
    // ====================================
    // Execute action with subsetted state
    const result = await concreteAction.run({
      state: forkedState,
      inputs
    });

    // ====================================
    // PHASE 3: GATHER
    // ====================================
    // Collect writes, validate against schema
    const writesState = concreteAction.update({
      result,
      state: forkedState,
      inputs
    });
    
    // Subset writes to only declared write fields
    const writeKeys = action.writes;
    const writes = writesState.subset(writeKeys);
    
    // ====================================
    // PHASE 4: COMMIT
    // ====================================
    // Merge writes back to committed state
    const newState = this.commitWrites(committedState, writes, action);
    
    return { action, result, newState };
  }
  
  /**
   * Commit writes to state (PHASE 4 of execution).
   * 
   * Merges action writes back into the committed state.
   * Validates that writes don't include reserved metadata keys.
   * 
   * Uses simple overwrite strategy: writes take precedence over existing values.
   * Future: Support parallel merge strategies with conflict resolution.
   * 
   * @internal
   */
  private commitWrites(
    committedState: ApplicationStateInstance<TStateSchema>,
    writes: StateInstance<any, any, any>,
    action: ActionLike<any, any, any, any>
  ): ApplicationStateInstance<TStateSchema> {
    // Validate no reserved metadata keys in writes
    const writeKeys = Object.keys(writes.data);
    const reservedWrites = writeKeys.filter(isReservedMetadataKey);
    if (reservedWrites.length > 0) {
      throw new Error(
        `Action '${action.name}' attempted to write to reserved metadata keys: ${reservedWrites.join(', ')}. ` +
        `Keys ending in 'Metadata' are reserved for framework use.`
      );
    }
    
    // Simple overwrite merge: writes take precedence
    const mergedData = {
      ...committedState.data,
      ...writes.data
    };
    
    return committedState.update(mergedData as any) as ApplicationStateInstance<TStateSchema>;
  }
  
  /**
   * Executes a single step of the application.
   * 
   * Advances the state machine by one action, executing the next action
   * based on the current state and transitions.
   * 
   * @param options - Execution options (inputs, halt conditions)
   * @returns StepResult containing the action, result, and new state.
   *          Returns null if there is no next action to execute.
   * 
   * @example
   * ```typescript
   * const step = await app.step({ inputs: { userId: '123' } });
   * if (step) {
   *   console.log(`Action:`, step.action.name);
   *   console.log(`Result:`, step.result);
   * }
   * ```
   */
  async step(options?: ExecutionOptions): Promise<StepResult<TStateSchema> | null> {
    return this._withExecuteCall('step', () => this._stepInternal(options));
  }

  /** @internal */
  private async _stepInternal(options?: ExecutionOptions): Promise<StepResult<TStateSchema> | null> {
    const inputs = options?.inputs || {};

    // Increment sequence ID before execution
    this.incrementSequenceId();

    // Get next action
    const nextAction = this.getNextAction();
    if (!nextAction) {
      return null; // Terminal state
    }

    const sequenceId = this.executionMetadata.sequenceId;

    // Pre-run hook
    await this._adapterSet.callPreRunStep({
      appId: this.appId,
      partitionKey: this.partitionKey,
      sequenceId,
      state: this._state,
      action: nextAction,
      inputs,
    });

    let exception: Error | null = null;
    try {
      // Execute the four-phase cycle: fork → launch → gather → commit
      const { action, result, newState } = await this.runStep(nextAction, inputs);

      // Update application state
      this._state = newState;
      this.setPriorStep(action.name || 'unknown');

      // Post-run hook (success)
      await this._adapterSet.callPostRunStep({
        appId: this.appId,
        partitionKey: this.partitionKey,
        sequenceId,
        state: this._state,
        action,
        result,
        exception: null,
      });

      return {
        action,
        result,
        state: this._state
      };
    } catch (error) {
      exception = error instanceof Error ? error : new Error(String(error));

      // Post-run hook (failure)
      await this._adapterSet.callPostRunStep({
        appId: this.appId,
        partitionKey: this.partitionKey,
        sequenceId,
        state: this._state,
        action: nextAction,
        result: null,
        exception,
      });

      const actionName = nextAction.name || 'unknown';
      throw new Error(`Error executing action '${actionName}': ${exception.message}`, { cause: exception });
    }
  }

  /**
   * Runs the application to completion.
   * 
   * Executes steps until a terminal state is reached or a halt condition is met.
   * Does not provide intermediate state access - use iterate() if you need that.
   * 
   * @param options - Execution options (inputs, haltBefore, haltAfter)
   * @returns RunResult containing the final action, result, and state
   * 
   * @example
   * ```typescript
   * const result = await app.run({
   *   inputs: { userId: '123' },
   *   haltAfter: ['final_action']
   * });
   * console.log(`Final state:`, result.state.data);
   * ```
   */
  async run(options?: ExecutionOptions): Promise<RunResult<TStateSchema>> {
    return this._withExecuteCall('run', () => this._runInternal(options));
  }

  /** @internal */
  private async _runInternal(options?: ExecutionOptions): Promise<RunResult<TStateSchema>> {
    const haltBefore = options?.haltBefore || [];
    const haltAfter = options?.haltAfter || [];
    const inputs = options?.inputs || {};

    let lastAction: ActionLike<any, any, any, any> | null = null;
    let lastResult: Record<string, any> | void | null = null;
    
    while (true) {
      // Check halt_before condition
      const nextAction = this.getNextAction();
      if (nextAction && haltBefore.includes(nextAction.name || '')) {
        // Halt before executing this action
        return {
          action: nextAction,
          result: null, // Didn't execute, so no result
          state: this._state
        };
      }
      
      // Execute a step (use _stepInternal to avoid double execute-call hooks)
      const stepResult = await this._stepInternal({ inputs });

      // If terminal (no more actions), return
      if (!stepResult) {
        return {
          action: lastAction,
          result: lastResult,
          state: this._state
        };
      }

      // Update tracking
      lastAction = stepResult.action;
      lastResult = stepResult.result;

      // Check halt_after condition
      if (haltAfter.includes(stepResult.action.name || '')) {
        return {
          action: stepResult.action,
          result: stepResult.result,
          state: stepResult.state
        };
      }
    }
  }

  /**
   * Iterates through the application execution, yielding each step.
   * 
   * Returns an async iterable that yields StepResult for each executed action.
   * This allows you to observe state changes as they happen.
   * 
   * @param options - Execution options (inputs, halt conditions)
   * @returns AsyncIterable that yields StepResult for each step
   * 
   * @example
   * ```typescript
   * for await (const step of app.iterate({
   *   inputs: { userId: '123' },
   *   haltAfter: ['final_action']
   * })) {
   *   console.log(`State:`, step.state.data);
   *   console.log(`Next:`, step.next);
   * }
   * ```
   */
  async *iterate(options?: ExecutionOptions): AsyncIterable<StepResult<TStateSchema>> {
    // Pre execute-call hook
    await this._adapterSet.callPreExecuteCall({
      appId: this.appId, partitionKey: this.partitionKey,
      state: this._state, method: 'iterate',
    });

    let iterateException: Error | null = null;
    try {
      const haltBefore = options?.haltBefore || [];
      const haltAfter = options?.haltAfter || [];
      const inputs = options?.inputs || {};

      while (true) {
        const nextAction = this.getNextAction();
        if (nextAction && haltBefore.includes(nextAction.name || '')) {
          break;
        }

        // Use _stepInternal to avoid double execute-call hooks
        const stepResult = await this._stepInternal({ inputs });

        if (!stepResult) {
          break;
        }

        yield stepResult;

        if (haltAfter.includes(stepResult.action.name || '')) {
          break;
        }
      }
    } catch (e) {
      iterateException = e instanceof Error ? e : new Error(String(e));
      throw e;
    } finally {
      await this._adapterSet.callPostExecuteCall({
        appId: this.appId, partitionKey: this.partitionKey,
        state: this._state, method: 'iterate', exception: iterateException,
      });
    }
  }

  /**
   * Execute a streaming step.
   *
   * If the next action is a StreamingAction, returns a StreamingResultContainer
   * that can be iterated over for intermediate results. After iteration completes,
   * the state is committed.
   *
   * If the next action is a regular (non-streaming) Action, runs it to completion
   * and wraps the result in a StreamingResultContainer for a uniform API.
   *
   * @param options - Execution options (inputs)
   * @returns Object with action and streaming container, or null if terminal
   *
   * @example
   * ```typescript
   * const streamResult = await app.streamStep();
   * if (streamResult) {
   *   for await (const chunk of streamResult.stream) {
   *     console.log(chunk.token);
   *   }
   *   const { result, state } = await streamResult.stream.get();
   * }
   * ```
   */
  async streamStep(options?: ExecutionOptions): Promise<{
    action: ActionLike<any, any, any, any>;
    stream: StreamingResultContainer<any>;
  } | null> {
    return this._withExecuteCall('streamStep', () => this._streamStepInternal(options));
  }

  /** @internal */
  private async _streamStepInternal(options?: ExecutionOptions): Promise<{
    action: ActionLike<any, any, any, any>;
    stream: StreamingResultContainer<any>;
  } | null> {
    const inputs = options?.inputs || {};

    // Increment sequence ID
    this.incrementSequenceId();

    // Get next action
    const nextAction = this.getNextAction();
    if (!nextAction) {
      return null;
    }

    const sequenceId = this.executionMetadata.sequenceId;

    // Pre-run hook
    await this._adapterSet.callPreRunStep({
      appId: this.appId,
      partitionKey: this.partitionKey,
      sequenceId,
      state: this._state,
      action: nextAction as Action<any, any, any, any>,
      inputs,
    });

    if (isStreamingAction(nextAction)) {
      // Streaming path
      const committedState = this._state;
      const forkedState = committedState.subset(nextAction.reads) as StateInstance<any, any, any>;

      const rawGenerator = nextAction.streamRun({ state: forkedState, inputs });

      // Wrap the generator to fire stream lifecycle hooks
      const actionName = nextAction.name || 'unknown';
      const adapterSet = this._adapterSet;
      const appId = this.appId;
      const partitionKey = this.partitionKey;
      const streamInitializeTime = new Date();

      async function* wrappedGenerator(): AsyncGenerator<any, void, undefined> {
        // Pre-start stream hook
        await adapterSet.callPreStartStream({
          action: actionName, sequenceId, appId, partitionKey,
        });

        let itemIndex = 0;
        let firstItemTime: Date | undefined;
        try {
          for await (const item of rawGenerator) {
            if (itemIndex === 0) firstItemTime = new Date();

            // Post-stream-item hook
            await adapterSet.callPostStreamItem({
              item, itemIndex,
              streamInitializeTime,
              firstStreamItemStartTime: firstItemTime!,
              action: actionName, sequenceId, appId, partitionKey,
            });

            yield item;
            itemIndex++;
          }
        } finally {
          // Post-end stream hook
          await adapterSet.callPostEndStream({
            action: actionName, sequenceId, appId, partitionKey,
          });
        }
      }

      const container = new StreamingResultContainer(
        wrappedGenerator(),
        forkedState,
        (result, state) => {
          const writesState = nextAction.update({ result, state, inputs });
          const writeKeys = nextAction.writes;
          const writes = writesState.subset(writeKeys);
          const newState = this.commitWrites(committedState, writes, nextAction as any);

          this._state = newState;
          this.setPriorStep(actionName);

          // Post-run hook (fire-and-forget inside container finalization)
          void this._adapterSet.callPostRunStep({
            appId: this.appId,
            partitionKey: this.partitionKey,
            sequenceId,
            state: this._state,
            action: nextAction as any,
            result,
            exception: null,
          });

          return this._state;
        },
      );

      return { action: nextAction, stream: container };
    } else {
      // Non-streaming path: run to completion, wrap in container
      try {
        const { action: executedAction, result, newState } = await this.runStep(nextAction, inputs);
        this._state = newState;
        this.setPriorStep(executedAction.name || 'unknown');

        await this._adapterSet.callPostRunStep({
          appId: this.appId,
          partitionKey: this.partitionKey,
          sequenceId,
          state: this._state,
          action: executedAction,
          result,
          exception: null,
        });

        // Wrap in a pass-through container
        const container = StreamingResultContainer.passThrough(result as any, this._state);
        return { action: executedAction, stream: container };
      } catch (error) {
        const exception = error instanceof Error ? error : new Error(String(error));

        await this._adapterSet.callPostRunStep({
          appId: this.appId,
          partitionKey: this.partitionKey,
          sequenceId,
          state: this._state,
          action: nextAction,
          result: null,
          exception,
        });

        throw new Error(
          `Error executing action '${nextAction.name || 'unknown'}': ${exception.message}`,
          { cause: exception }
        );
      }
    }
  }

  /**
   * Wraps an execute method with pre/post execute-call hooks.
   * Mirrors Python's pattern of calling pre_run_execute_call / post_run_execute_call
   * around step/run/iterate/stream methods.
   * @internal
   */
  private async _withExecuteCall<T>(method: ExecuteMethod, fn: () => Promise<T>): Promise<T> {
    await this._adapterSet.callPreExecuteCall({
      appId: this.appId,
      partitionKey: this.partitionKey,
      state: this._state,
      method,
    });

    let exception: Error | null = null;
    try {
      return await fn();
    } catch (e) {
      exception = e instanceof Error ? e : new Error(String(e));
      throw e;
    } finally {
      await this._adapterSet.callPostExecuteCall({
        appId: this.appId,
        partitionKey: this.partitionKey,
        state: this._state,
        method,
        exception,
      });
    }
  }
}

