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

// Application builder with fluent API

import { z } from 'zod';
import { Graph } from './graph';
import { StateInstance } from './state';
import { Application } from './application';
import {
  UseIfNotSet,
  EnsureRecordSchema,
  ConditionalValidate
} from './type-utils';
import { type LifecycleAdapter, LifecycleAdapterSet, isPostApplicationCreateHook } from './lifecycle';
import { PersisterHook, type StateSaver, type StateLoader } from './persistence';
import { deserializeState, type SerdeOptions } from './serde';

/**
 * Selects final schema: if app schema not set, use graph schema; otherwise use app schema.
 * Domain-specific utility for ApplicationBuilder.build() method.
 */
type SelectFinalSchema<
  TAppSchema extends z.ZodType,
  TGraphSchema extends z.ZodType
> = [TAppSchema] extends [z.ZodNever]
  ? [TGraphSchema] extends [z.ZodNever]
    ? z.ZodNever
    : TGraphSchema
  : TAppSchema;

/**
 * Validates schema compatibility and returns either SuccessType or error type.
 * Avoids duplication of ConditionalValidate calls in method signatures.
 * 
 * @param AllowOptional - If true, allows TNew to have optional fields where TExisting has required fields
 */
type ValidatedOrError<
  TNew extends z.ZodType,
  TExisting extends z.ZodType,
  SuccessType,
  ErrorMsg extends string = '❌ Schema constraint violation',
  AllowOptional extends boolean = false
> = ConditionalValidate<TNew, TExisting, ErrorMsg, AllowOptional> extends z.ZodType
  ? SuccessType
  : ConditionalValidate<TNew, TExisting, ErrorMsg, AllowOptional>;

/**
 * Immutable builder for constructing applications.
 * Each method returns a new builder instance.
 * 
 * Separates concerns:
 * - Graph defines structure (actions + transitions) and computes required state schema
 * - ApplicationBuilder defines runtime (entrypoint + initial state) and validates state
 * 
 * Type safety:
 * - TAppStateSchema: The application's state schema (from explicit generic or withState)
 * - TGraphStateSchema: The graph's required state schema (computed from actions)
 * - Validation: TAppStateSchema must extend TGraphStateSchema (application state is superset of graph requirements)
 * 
 * @template TAppStateSchema - Application state schema type (defaults to never for inference)
 * @template TGraphStateSchema - Graph's required state schema type (internal, set by withGraph)
 */
export class ApplicationBuilder<
  TAppStateSchema extends z.ZodType | z.ZodNever = z.ZodNever,
  TGraphStateSchema extends z.ZodType | z.ZodNever = z.ZodNever
> {
  private readonly _graph: Graph<TGraphStateSchema> | null;
  private readonly _entrypoint: string | null;
  private readonly _initialState: StateInstance<any, any, any> | null;
  private readonly _appId: string | null;
  private readonly _partitionKey: string | undefined;
  private readonly _initialSequenceId: number | undefined;
  private readonly _lifecycleAdapters: readonly LifecycleAdapter[];

  constructor(
    graph: Graph<TGraphStateSchema> | null = null,
    entrypoint: string | null = null,
    initialState: StateInstance<any, any, any> | null = null,
    appId: string | null = null,
    partitionKey: string | undefined = undefined,
    initialSequenceId: number | undefined = undefined,
    lifecycleAdapters: readonly LifecycleAdapter[] = []
  ) {
    this._graph = graph;
    this._entrypoint = entrypoint;
    this._initialState = initialState;
    this._appId = appId;
    this._partitionKey = partitionKey;
    this._initialSequenceId = initialSequenceId;
    this._lifecycleAdapters = lifecycleAdapters;
  }

  /**
   * Set the graph for this application.
   * The graph defines the structure (actions and transitions) and required state schema.
   * 
   * When TAppStateSchema is not set (never), infers from graph.
   * Otherwise, validates at compile-time that TAppStateSchema's inferred type extends TNewGraphStateSchema's inferred type.
   * 
   * @param graph - Graph built with GraphBuilder
   * @returns New ApplicationBuilder instance with graph set
   * @throws Error if graph is already set or state incompatible with graph
   * 
   * @example
   * ```typescript
   * const app = new ApplicationBuilder()
   *   .withGraph(myGraph)
   *   .withEntrypoint('start')
   *   .withState(initialState)
   *   .build();
   * ```
   */
  withGraph<TNewGraphStateSchema extends z.ZodType<Record<string, any>>>(
    graph: ValidatedOrError<
      TAppStateSchema,
      TNewGraphStateSchema,
      Graph<TNewGraphStateSchema>,
      '❌ State schema must extend graph requirements'
    >
  ): ApplicationBuilder<
    UseIfNotSet<TAppStateSchema, TNewGraphStateSchema>,
    TNewGraphStateSchema
  > {
    if (this._graph !== null) {
      throw new Error(
        'Graph is already set. ApplicationBuilder.withGraph() can only be called once.'
      );
    }

    // Type guard to ensure graph is actually a Graph, not an error type
    if (!('actions' in graph)) {
      throw new Error('Invalid graph provided');
    }

    return new ApplicationBuilder<
      UseIfNotSet<TAppStateSchema, TNewGraphStateSchema>,
      TNewGraphStateSchema
    >(
      graph as Graph<TNewGraphStateSchema>,
      this._entrypoint,
      this._initialState,
      this._appId,
      this._partitionKey,
      this._initialSequenceId,
      this._lifecycleAdapters
    );
  }

  /**
   * Set the entrypoint action for this application.
   * This is the first action that will be executed.
   * 
   * @param actionName - Name of the action to start at
   * @returns New ApplicationBuilder instance with entrypoint set
   * @throws Error if entrypoint is already set or if graph is not set
   * 
   * @example
   * ```typescript
   * builder.withEntrypoint('myStartAction')
   * ```
   */
  withEntrypoint(actionName: string): ApplicationBuilder<TAppStateSchema, TGraphStateSchema> {
    if (this._entrypoint !== null) {
      throw new Error(
        'Entrypoint is already set. ApplicationBuilder.withEntrypoint() can only be called once.'
      );
    }

    if (this._graph === null) {
      throw new Error(
        'Graph must be set before entrypoint. Call withGraph() first.'
      );
    }

    // Validate entrypoint exists in graph
    if (!this._graph.hasAction(actionName)) {
      const availableActions = this._graph.getActionNames();
      throw new Error(
        `Entrypoint action '${actionName}' not found in graph. ` +
        `Available actions: ${availableActions.join(', ')}`
      );
    }

    return new ApplicationBuilder<TAppStateSchema, TGraphStateSchema>(
      this._graph,
      actionName,
      this._initialState,
      this._appId,
      this._partitionKey,
      this._initialSequenceId,
      this._lifecycleAdapters
    );
  }

  /**
   * Set the initial state for this application.
   * 
   * When TAppStateSchema is not set (never), infers from state schema.
   * Validates at compile-time that state schema has all graph fields (if graph is set).
   * Allows state to have optional fields where graph requires them (e.g., fields created by actions).
   * 
   * @param initialState - State instance created with createState()
   * @returns New ApplicationBuilder instance with state set
   * @throws Error if state is already set or state doesn't match graph requirements
   * 
   * @example
   * ```typescript
   * // State can have optional fields that graph requires
   * const state = createState(
   *   z.object({ count: z.number(), level: z.string().optional() }),
   *   { count: 0 }  // level will be created by an action
   * );
   * builder.withState(state)
   * ```
   */
  withState<TNewStateSchema extends z.ZodType<Record<string, any>>>(
    initialState: ValidatedOrError<
      TNewStateSchema,
      TGraphStateSchema,
      StateInstance<TNewStateSchema, TNewStateSchema, TNewStateSchema>,
      '❌ State schema must extend graph requirements',
      true  // Allow optional fields in state
    >
  ): ApplicationBuilder<
    UseIfNotSet<TAppStateSchema, TNewStateSchema>,
    TGraphStateSchema
  > {
    if (this._initialState !== null) {
      throw new Error(
        'Initial state is already set. ApplicationBuilder.withState() can only be called once.'
      );
    }

    return new ApplicationBuilder<
      UseIfNotSet<TAppStateSchema, TNewStateSchema>,
      TGraphStateSchema
    >(
      this._graph,
      this._entrypoint,
      initialState as any,
      this._appId,
      this._partitionKey,
      this._initialSequenceId,
      this._lifecycleAdapters
    );
  }

  /**
   * Set application identifiers (appId, partitionKey, initialSequenceId).
   * 
   * @param appId - Unique identifier for this application instance (auto-generated if not provided)
   * @param partitionKey - Optional partition key for grouping/querying application runs
   * @param initialSequenceId - Optional initial sequence ID (defaults to 0)
   * 
   * @example
   * ```typescript
   * const app = new ApplicationBuilder()
   *   .withIdentifiers('my-app-123', 'user-456')
   *   .withGraph(graph)
   *   .withState(initialState)
   *   .withEntrypoint('start')
   *   .build();
   * ```
   */
  withIdentifiers(
    appId?: string,
    partitionKey?: string,
    initialSequenceId?: number
  ): ApplicationBuilder<TAppStateSchema, TGraphStateSchema> {
    return new ApplicationBuilder<TAppStateSchema, TGraphStateSchema>(
      this._graph,
      this._entrypoint,
      this._initialState,
      appId ?? this._appId,
      partitionKey ?? this._partitionKey,
      initialSequenceId ?? this._initialSequenceId,
      this._lifecycleAdapters
    );
  }

  /**
   * Add lifecycle hooks to the application.
   *
   * Hooks are called at specific points during execution:
   * - preRunStep: before each action executes
   * - postRunStep: after each action completes (or fails)
   * - postApplicationCreate: after build() constructs the Application
   *
   * Multiple calls accumulate adapters (does not replace).
   *
   * @param adapters - One or more lifecycle adapters
   * @returns New ApplicationBuilder instance with hooks added
   *
   * @example
   * ```typescript
   * const logger: LifecycleAdapter = {
   *   async preRunStep({ action }) { console.log(`Running ${action.name}`); },
   *   async postRunStep({ action, exception }) {
   *     if (exception) console.error(`Failed: ${action.name}`);
   *     else console.log(`Done: ${action.name}`);
   *   }
   * };
   * builder.withHooks(logger)
   * ```
   */
  withHooks(
    ...adapters: LifecycleAdapter[]
  ): ApplicationBuilder<TAppStateSchema, TGraphStateSchema> {
    return new ApplicationBuilder<TAppStateSchema, TGraphStateSchema>(
      this._graph,
      this._entrypoint,
      this._initialState,
      this._appId,
      this._partitionKey,
      this._initialSequenceId,
      [...this._lifecycleAdapters, ...adapters]
    );
  }

  /**
   * Add a state persister that saves state after each step.
   *
   * This wraps the StateSaver as a PostRunStepHook using PersisterHook.
   * The persister saves serialized state after each action execution.
   *
   * @param saver - StateSaver implementation (e.g., InMemoryPersister)
   * @param serdeOptions - Optional custom serialization options
   * @returns New ApplicationBuilder instance with persister added
   */
  withStatePersister(
    saver: StateSaver,
    serdeOptions?: SerdeOptions
  ): ApplicationBuilder<TAppStateSchema, TGraphStateSchema> {
    const hook = new PersisterHook(saver, serdeOptions);
    return this.withHooks(hook);
  }

  /**
   * Initialize application state from a persisted checkpoint.
   *
   * Loads state from the given loader. If state is found, uses it as initial state
   * and optionally resumes at the next action. If not found, falls back to defaults.
   *
   * Mirrors Python's ApplicationBuilder.initialize_from().
   *
   * @param params.loader - StateLoader to load from
   * @param params.appId - App ID to load (uses builder's appId if not provided)
   * @param params.partitionKey - Partition key to load from
   * @param params.defaultState - Fallback state if nothing is persisted
   * @param params.defaultEntrypoint - Fallback entrypoint if nothing is persisted
   * @param params.resumeAtNextAction - If true, resume execution at the next action after the persisted position
   * @param params.forkFromAppId - Fork from a different app ID's state
   * @param params.forkFromSequenceId - Fork at a specific sequence ID
   * @param params.serdeOptions - Custom deserialization options
   */
  async initializeFrom(params: {
    loader: StateLoader;
    partitionKey: string;
    appId?: string;
    defaultState: StateInstance<any, any, any>;
    defaultEntrypoint: string;
    resumeAtNextAction?: boolean;
    forkFromAppId?: string;
    forkFromSequenceId?: number;
    serdeOptions?: SerdeOptions;
  }): Promise<ApplicationBuilder<TAppStateSchema, TGraphStateSchema>> {
    const loadAppId = params.forkFromAppId ?? params.appId ?? this._appId;
    const loaded = await params.loader.load(
      params.partitionKey,
      loadAppId,
      params.forkFromSequenceId
    );

    if (!loaded) {
      // No persisted state -- use defaults
      return new ApplicationBuilder<TAppStateSchema, TGraphStateSchema>(
        this._graph,
        params.defaultEntrypoint,
        params.defaultState as any,
        params.appId ?? this._appId,
        params.partitionKey ?? this._partitionKey,
        undefined,
        this._lifecycleAdapters
      );
    }

    // Deserialize persisted state
    const deserializedData = deserializeState(loaded.state, params.serdeOptions);

    // Create state from deserialized data
    const { createState } = await import('./state');
    const { z } = await import('zod');
    // Create a permissive schema that accepts any record
    const restoredState = createState(z.object({}).passthrough(), deserializedData);

    // Determine entrypoint
    let entrypoint: string;
    if (params.resumeAtNextAction) {
      // The persisted position is the last completed action.
      // We want to resume at whatever comes next, which means
      // setting priorStep so getNextAction() works correctly.
      // The entrypoint is not used when priorStep is set.
      entrypoint = params.defaultEntrypoint;
    } else {
      entrypoint = params.defaultEntrypoint;
    }

    return new ApplicationBuilder<TAppStateSchema, TGraphStateSchema>(
      this._graph,
      entrypoint,
      restoredState as any,
      params.forkFromAppId ? (params.appId ?? this._appId) : loadAppId,
      params.partitionKey ?? this._partitionKey,
      params.resumeAtNextAction ? loaded.sequenceId : undefined,
      this._lifecycleAdapters
    );
  }

  /**
   * Build the final application.
   * Validates that all required components are set.
   * 
   * If appId is not set, a random UUID will be generated.
   * 
   * @returns Immutable Application instance with typed state schema
   * @throws Error if graph, entrypoint, or state is not set
   * 
   * @example
   * ```typescript
   * const app = new ApplicationBuilder()
   *   .withGraph(graph)
   *   .withEntrypoint('start')
   *   .withState(initialState)
   *   .build();
   * ```
   */
  build(): Application<EnsureRecordSchema<SelectFinalSchema<TAppStateSchema, TGraphStateSchema>>> {
    // Validate all required components are set
    if (this._graph === null) {
      throw new Error(
        'Cannot build application without graph. Call withGraph() before build().'
      );
    }

    if (this._entrypoint === null) {
      throw new Error(
        'Cannot build application without entrypoint. Call withEntrypoint() before build().'
      );
    }

    if (this._initialState === null) {
      throw new Error(
        'Cannot build application without initial state. Call withState() before build().'
      );
    }

    // TODO: Validate initial state has entrypoint.reads fields
    // Current limitation: Graph fields are all optional, so we can't enforce at compile-time
    // that initial state has the fields required by entrypoint.
    // Runtime validation would catch this, but we'd lose IDE errors.
    // Future enhancement: Add runtime check or improve type system to track entrypoint schema.

    // Generate default appId if not provided
    const appId = this._appId ?? `app-${Date.now()}-${Math.random().toString(36).substring(2, 9)}`;

    // At runtime, we've validated that state and graph are set
    // Type assertion is safe because withState/withGraph enforce the constraint at the API boundary
    // EnsureRecordSchema ensures the constraint is satisfied
    type FinalStateSchema = EnsureRecordSchema<SelectFinalSchema<TAppStateSchema, TGraphStateSchema>>;

    const app = new Application(
      this._graph! as Graph<FinalStateSchema>,
      this._entrypoint!,
      this._initialState! as StateInstance<FinalStateSchema, FinalStateSchema, FinalStateSchema>,
      appId,
      this._partitionKey,
      this._initialSequenceId,
      [...this._lifecycleAdapters]
    ) as Application<FinalStateSchema>;

    // Fire postApplicationCreate hooks (async, but build() is sync -- schedule and don't await).
    // Callers who need to await this should use buildAsync().
    const adapterSet = new LifecycleAdapterSet([...this._lifecycleAdapters]);
    const hasPostCreate = this._lifecycleAdapters.some(isPostApplicationCreateHook);
    if (hasPostCreate) {
      // Schedule async hook dispatch -- errors are intentionally unhandled here.
      // Use buildAsync() if you need to catch postApplicationCreate errors.
      void adapterSet.callPostApplicationCreate({
        appId,
        partitionKey: this._partitionKey,
        state: app.state,
        graph: this._graph!,
        entrypoint: this._entrypoint!,
      });
    }

    return app;
  }

  /**
   * Build the application and await postApplicationCreate lifecycle hooks.
   *
   * Use this instead of build() when you have PostApplicationCreateHook adapters
   * and need to ensure they complete before proceeding.
   */
  async buildAsync(): Promise<Application<EnsureRecordSchema<SelectFinalSchema<TAppStateSchema, TGraphStateSchema>>>> {
    // Validate all required components are set
    if (this._graph === null) {
      throw new Error(
        'Cannot build application without graph. Call withGraph() before build().'
      );
    }
    if (this._entrypoint === null) {
      throw new Error(
        'Cannot build application without entrypoint. Call withEntrypoint() before build().'
      );
    }
    if (this._initialState === null) {
      throw new Error(
        'Cannot build application without initial state. Call withState() before build().'
      );
    }

    const appId = this._appId ?? `app-${Date.now()}-${Math.random().toString(36).substring(2, 9)}`;
    type FinalStateSchema = EnsureRecordSchema<SelectFinalSchema<TAppStateSchema, TGraphStateSchema>>;

    const app = new Application(
      this._graph! as Graph<FinalStateSchema>,
      this._entrypoint!,
      this._initialState! as StateInstance<FinalStateSchema, FinalStateSchema, FinalStateSchema>,
      appId,
      this._partitionKey,
      this._initialSequenceId,
      [...this._lifecycleAdapters]
    ) as Application<FinalStateSchema>;

    // Await postApplicationCreate hooks
    const adapterSet = new LifecycleAdapterSet([...this._lifecycleAdapters]);
    await adapterSet.callPostApplicationCreate({
      appId,
      partitionKey: this._partitionKey,
      state: app.state,
      graph: this._graph!,
      entrypoint: this._entrypoint!,
    });

    return app;
  }
}

