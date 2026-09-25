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

// Sub-graph execution and parallel task support.
//
// Mirrors Python's burr/core/parallelism.py.
// Uses Promise.all() instead of thread/process pools (async I/O bound).

import { Graph } from './graph';
import { StateInstance } from './state';
import { ApplicationBuilder } from './application-builder';
import { type StateSaver, type StateLoader } from './persistence';
import { type ActionLike } from './types';
import { type LifecycleAdapter } from './lifecycle';

// ============================================================================
// ApplicationContext
// ============================================================================

/**
 * Context passed from parent application to sub-graphs.
 * Carries identity and optional persistence/tracking references.
 *
 * Mirrors Python's ApplicationContext.
 */
export interface ApplicationContext {
  appId: string;
  partitionKey: string | undefined;
  sequenceId: number;
  statePersister?: StateSaver;
  stateLoader?: StateLoader;
  lifecycleAdapters?: LifecycleAdapter[];
}

// ============================================================================
// RunnableGraph
// ============================================================================

/**
 * A graph bundled with an entrypoint and halt conditions.
 * Can be executed as a standalone sub-application.
 *
 * Mirrors Python's RunnableGraph.
 */
export class RunnableGraph {
  readonly graph: Graph<any>;
  readonly entrypoint: string;
  readonly haltAfter: string[];

  constructor(graph: Graph<any>, entrypoint: string, haltAfter: string[]) {
    this.graph = graph;
    this.entrypoint = entrypoint;
    this.haltAfter = haltAfter;
  }

  /**
   * Create a RunnableGraph from an existing graph with explicit config.
   */
  static create(
    graph: Graph<any>,
    entrypoint: string,
    haltAfter: string[]
  ): RunnableGraph {
    return new RunnableGraph(graph, entrypoint, haltAfter);
  }
}

// ============================================================================
// SubGraphTask
// ============================================================================

/**
 * A single task that runs a sub-graph to completion.
 *
 * Mirrors Python's SubGraphTask.
 */
/**
 * Cascade behavior for persistence/tracking in sub-graphs.
 * Mirrors Python's StatePersisterBehavior / StateInitializerBehavior / TrackerBehavior.
 *
 * - 'cascade': inherit from parent context
 * - null: don't use
 * - object: use the specified instance
 */
export type CascadeBehavior<T> = 'cascade' | null | T;

export class SubGraphTask {
  readonly graph: RunnableGraph;
  readonly state: StateInstance<any, any, any>;
  readonly inputs: Record<string, any>;
  readonly applicationId: string;
  readonly statePersister?: StateSaver;
  readonly stateLoader?: StateLoader;
  readonly lifecycleAdapters?: LifecycleAdapter[];

  constructor(params: {
    graph: RunnableGraph;
    state: StateInstance<any, any, any>;
    inputs?: Record<string, any>;
    applicationId: string;
    statePersister?: StateSaver;
    stateLoader?: StateLoader;
    lifecycleAdapters?: LifecycleAdapter[];
  }) {
    this.graph = params.graph;
    this.state = params.state;
    this.inputs = params.inputs ?? {};
    this.applicationId = params.applicationId;
    this.statePersister = params.statePersister;
    this.stateLoader = params.stateLoader;
    this.lifecycleAdapters = params.lifecycleAdapters;
  }

  /**
   * Run the sub-graph to completion and return the final state.
   * Cascades persistence and lifecycle adapters from parent context.
   */
  async run(parentContext?: ApplicationContext): Promise<StateInstance<any, any, any>> {
    let builder = new ApplicationBuilder()
      .withGraph(this.graph.graph)
      .withState(this.state)
      .withEntrypoint(this.graph.entrypoint)
      .withIdentifiers(
        this.applicationId,
        parentContext?.partitionKey
      );

    // Cascade persistence from parent if not explicitly set
    const persister = this.statePersister ?? parentContext?.statePersister;
    if (persister) {
      builder = builder.withStatePersister(persister);
    }

    // Cascade lifecycle adapters from parent if not explicitly set
    const adapters = this.lifecycleAdapters ?? parentContext?.lifecycleAdapters;
    if (adapters && adapters.length > 0) {
      builder = builder.withHooks(...adapters);
    }

    const app = builder.build();

    const result = await app.run({
      inputs: this.inputs,
      haltAfter: this.graph.haltAfter,
    });

    return result.state;
  }
}

// ============================================================================
// TaskBasedParallelAction (Abstract Base)
// ============================================================================

/**
 * Abstract base for actions that spawn and run multiple sub-graphs in parallel.
 *
 * Users implement:
 * 1. `tasks()` - generate the sub-graph tasks to run
 * 2. `reduce()` - merge results from all sub-graphs into final state
 *
 * Execution uses Promise.all() for concurrent I/O-bound tasks.
 *
 * Mirrors Python's TaskBasedParallelAction.
 */
export abstract class TaskBasedParallelAction {
  abstract get reads(): readonly string[];
  abstract get writes(): readonly string[];

  /**
   * Generate the tasks to execute in parallel.
   */
  abstract tasks(
    state: StateInstance<any, any, any>,
    context: ApplicationContext,
    inputs: Record<string, any>
  ): SubGraphTask[] | Promise<SubGraphTask[]>;

  /**
   * Reduce the results from parallel tasks into the final state.
   *
   * @param state - The state before parallel execution
   * @param states - Array of final states from each sub-graph
   * @returns The merged/reduced state
   */
  abstract reduce(
    state: StateInstance<any, any, any>,
    states: StateInstance<any, any, any>[]
  ): StateInstance<any, any, any>;

  /**
   * Cascade behavior: what persister does the sub-application use?
   * 'cascade' = inherit from parent, null = don't use, or provide a specific instance.
   */
  statePersister(): CascadeBehavior<StateSaver> { return 'cascade'; }

  /**
   * Cascade behavior: what loader does the sub-application use?
   */
  stateLoader(): CascadeBehavior<StateLoader> { return 'cascade'; }

  /**
   * Cascade behavior: what lifecycle adapters does the sub-application use?
   */
  lifecycleAdapters(): CascadeBehavior<LifecycleAdapter[]> { return 'cascade'; }

  /**
   * Execute: gather tasks, run in parallel, reduce.
   */
  async execute(
    state: StateInstance<any, any, any>,
    context: ApplicationContext,
    inputs: Record<string, any> = {}
  ): Promise<{ state: StateInstance<any, any, any> }> {
    // 1. Generate tasks
    const taskList = await this.tasks(state, context, inputs);

    // 2. Run all tasks concurrently
    const resultStates = await Promise.all(
      taskList.map(task => task.run(context))
    );

    // 3. Reduce results
    const finalState = this.reduce(state, resultStates);

    return { state: finalState };
  }

  /** @internal Resolve cascade behavior for a given field. */
  protected _cascade<T>(behavior: CascadeBehavior<T>, parentValue: T | undefined): T | undefined {
    if (behavior === 'cascade') return parentValue;
    if (behavior === null) return undefined;
    return behavior;
  }
}

// ============================================================================
// MapActionsAndStates
// ============================================================================

/**
 * Cartesian product of actions x states.
 * Mirrors Python's MapActionsAndStates.
 *
 * User implements:
 * - actions(): yields actions or RunnableGraphs to run
 * - states(): yields state variants to run each action with
 * - reduce(): merges results
 *
 * @example
 * ```typescript
 * class TestModelsOverPrompts extends MapActionsAndStates {
 *   actions(state, context, inputs) {
 *     return [gpt4Action, claudeAction, o1Action];
 *   }
 *   states(state, context, inputs) {
 *     return prompts.map(p => state.update({ prompt: p }));
 *   }
 *   reduce(state, states) {
 *     return state.update({ results: states.map(s => s.output) });
 *   }
 *   get reads() { return ['prompts']; }
 *   get writes() { return ['results']; }
 * }
 * ```
 */
export abstract class MapActionsAndStates extends TaskBasedParallelAction {
  /**
   * Yields actions (or RunnableGraphs) to run in parallel.
   */
  abstract actions(
    state: StateInstance<any, any, any>,
    context: ApplicationContext,
    inputs: Record<string, any>
  ): (ActionLike<any, any, any, any> | RunnableGraph)[] | Promise<(ActionLike<any, any, any, any> | RunnableGraph)[]>;

  /**
   * Yields state variants to run each action with.
   */
  abstract states(
    state: StateInstance<any, any, any>,
    context: ApplicationContext,
    inputs: Record<string, any>
  ): StateInstance<any, any, any>[] | Promise<StateInstance<any, any, any>[]>;

  async tasks(
    state: StateInstance<any, any, any>,
    context: ApplicationContext,
    inputs: Record<string, any>
  ): Promise<SubGraphTask[]> {
    const actionList = await this.actions(state, context, inputs);
    const stateList = await this.states(state, context, inputs);
    const tasks: SubGraphTask[] = [];

    for (let i = 0; i < actionList.length; i++) {
      for (let j = 0; j < stateList.length; j++) {
        const act = actionList[i];
        const substate = stateList[j];
        let graph: RunnableGraph;
        if (act instanceof RunnableGraph) {
          graph = act;
        } else {
          const { graph: singleGraph, name } = _singleActionGraph(act);
          graph = RunnableGraph.create(singleGraph, name, [name]);
        }

        tasks.push(new SubGraphTask({
          graph,
          state: substate,
          inputs,
          applicationId: _stableAppIdHash(context.appId, `${i}-${j}`),
          statePersister: this._cascade(this.statePersister(), context.statePersister) ?? undefined,
          stateLoader: this._cascade(this.stateLoader(), context.stateLoader) ?? undefined,
          lifecycleAdapters: this._cascade(this.lifecycleAdapters(), context.lifecycleAdapters) ?? undefined,
        }));
      }
    }

    return tasks;
  }
}

// ============================================================================
// MapActions
// ============================================================================

/**
 * Run multiple actions over the same state.
 * Mirrors Python's MapActions.
 *
 * User implements:
 * - actions(): yields actions to run
 * - reduce(): merges results
 * - Optionally override state() to transform the input state
 */
export abstract class MapActions extends MapActionsAndStates {
  abstract actions(
    state: StateInstance<any, any, any>,
    context: ApplicationContext,
    inputs: Record<string, any>
  ): (ActionLike<any, any, any, any> | RunnableGraph)[] | Promise<(ActionLike<any, any, any, any> | RunnableGraph)[]>;

  /**
   * The state to use for all actions. Defaults to the input state.
   * Override to transform the state before passing to sub-actions.
   */
  state(
    state: StateInstance<any, any, any>,
    _inputs: Record<string, any>
  ): StateInstance<any, any, any> {
    return state;
  }

  states(
    state: StateInstance<any, any, any>,
    _context: ApplicationContext,
    inputs: Record<string, any>
  ): StateInstance<any, any, any>[] {
    return [this.state(state, inputs)];
  }
}

// ============================================================================
// MapStates
// ============================================================================

/**
 * Run a single action over multiple state variants.
 * Mirrors Python's MapStates.
 *
 * User implements:
 * - action(): returns the single action to run
 * - states(): yields state variants
 * - reduce(): merges results
 */
export abstract class MapStates extends MapActionsAndStates {
  /**
   * The single action to apply to each state variant.
   */
  abstract action(
    state: StateInstance<any, any, any>,
    inputs: Record<string, any>
  ): ActionLike<any, any, any, any> | RunnableGraph;

  abstract states(
    state: StateInstance<any, any, any>,
    context: ApplicationContext,
    inputs: Record<string, any>
  ): StateInstance<any, any, any>[] | Promise<StateInstance<any, any, any>[]>;

  actions(
    state: StateInstance<any, any, any>,
    _context: ApplicationContext,
    inputs: Record<string, any>
  ): (ActionLike<any, any, any, any> | RunnableGraph)[] {
    return [this.action(state, inputs)];
  }
}

// ============================================================================
// Helpers
// ============================================================================

/**
 * Create a single-action graph for wrapping an action in a RunnableGraph.
 * @internal
 */
function _singleActionGraph(act: ActionLike<any, any, any, any>): { graph: Graph<any>; name: string } {
  const { GraphBuilder } = require('./graph');
  const name = act.name ?? `action_${_actionCounter++}`;
  const namedAct = act.name ? act : act.withName(name);
  const graph = new GraphBuilder()
    .withActions({ [name]: namedAct })
    .withTransitions([name, null])
    .build();
  return { graph, name };
}

let _actionCounter = 0;

/**
 * Stable hash for child application IDs.
 * Mirrors Python's _stable_app_id_hash.
 * @internal
 */
function _stableAppIdHash(parentAppId: string, key: string): string {
  return `${parentAppId}:sub:${key}`;
}
