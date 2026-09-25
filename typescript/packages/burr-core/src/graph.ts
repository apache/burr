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

// Graph structure and transition logic

import { z } from 'zod';
import { FixEmptySchema, MergeRecordValues } from './type-utils';
import { type ActionLike } from './types';

// ============================================================================
// Type Utilities
// ============================================================================

/**
 * Merges all state fields from actions into a single type.
 * 
 * Graph type represents the FINAL state - all fields are REQUIRED.
 * This ensures transition conditions can safely access fields without undefined checks.
 * 
 * Initial state can be a subset (some fields optional), but graph defines the complete contract.
 * 
 * Example:
 * - Action1 reads/writes: {a: number}
 * - Action2 reads/writes: {b: string}
 * - Result: {a: number, b: string}  (both required in final state)
 */
type MergeActionStates<TActions extends Record<string, ActionLike<any, any, any, any>>> =
  MergeRecordValues<{
    [K in keyof TActions]:
      TActions[K] extends ActionLike<infer R, infer W, any, any>
        ? FixEmptySchema<z.infer<R>> & FixEmptySchema<z.infer<W>>
        : never
  }>;

/**
 * Infers the state type based on builder mode:
 * - Bottom-up (default): Compute from actions
 * - Top-down: Use provided schema
 */
type InferStateType<
  TStateSchema extends z.ZodType,
  TActions extends Record<string, ActionLike<any, any, any, any>>
> = TStateSchema extends z.ZodNever
  ? MergeActionStates<TActions>
  : z.infer<TStateSchema>;

/**
 * Converts an inferred state type to a Zod schema type.
 * For bottom-up mode, creates a type-level schema representation.
 */
type StateTypeToSchema<TStateType> = z.ZodType<TStateType>;

/**
 * Type for transition condition functions.
 */
type TransitionCondition<TState> = (state: TState) => boolean | Promise<boolean>;

// ============================================================================
// Transition Interface
// ============================================================================

/**
 * Represents a transition between actions in the graph.
 * Transitions are directed edges with optional conditions.
 */
export interface Transition {
  /** Source action name */
  readonly from: string;
  
  /** Target action name, or null for terminal transitions */
  readonly to: string | null;
  
  /** Optional condition function that determines if transition should be taken */
  readonly condition?: TransitionCondition<any>;
}

// ============================================================================
// Graph Class (Immutable Data Container)
// ============================================================================

/**
 * Represents a directed graph of actions and transitions.
 * This is an immutable data structure - no execution logic, just storage and query.
 * 
 * @template TStateSchema - The Zod object schema type for the state (union of all action reads/writes)
 */
export class Graph<TStateSchema extends z.ZodType = z.ZodNever> {
  /** Immutable map of action names to actions */
  readonly actions: ReadonlyMap<string, ActionLike<any, any, any, any>>;

  /** Immutable array of transitions */
  readonly transitions: readonly Transition[];

  /** @internal Type-level field for state schema tracking (not used at runtime) */
  // @ts-expect-error - This field is only for type-level tracking, not used at runtime
  private readonly _stateSchema!: TStateSchema;

  constructor(
    actions: Record<string, ActionLike<any, any, any, any>>,
    transitions: Transition[]
  ) {
    this.actions = new Map(Object.entries(actions));
    this.transitions = Object.freeze([...transitions]);
  }

  /**
   * Check if an action exists in the graph.
   */
  hasAction(name: string): boolean {
    return this.actions.has(name);
  }

  /**
   * Get an action by name.
   */
  getAction(name: string): ActionLike<any, any, any, any> | undefined {
    return this.actions.get(name);
  }

  /**
   * Get all transitions originating from a specific action.
   */
  getTransitionsFrom(actionName: string): readonly Transition[] {
    return this.transitions.filter(t => t.from === actionName);
  }

  /**
   * Get all action names in the graph.
   */
  getActionNames(): string[] {
    return Array.from(this.actions.keys());
  }

  /**
   * Get the number of actions in the graph.
   */
  get actionCount(): number {
    return this.actions.size;
  }

  /**
   * Get the number of transitions in the graph.
   */
  get transitionCount(): number {
    return this.transitions.length;
  }
}

// ============================================================================
// GraphBuilder Class (Immutable Builder)
// ============================================================================

/**
 * Immutable builder for constructing graphs.
 * Each method returns a new builder instance with updated types.
 * 
 * Supports two modes:
 * - Bottom-up (default): State type computed from actions
 * - Top-down: State type enforced by provided schema (future)
 * 
 * @template TStateSchema - Optional state schema for top-down mode
 * @template TActions - Accumulated actions with their types
 */
export class GraphBuilder<
  TStateSchema extends z.ZodType = z.ZodNever,
  TActions extends Record<string, ActionLike<any, any, any, any>> = {}
> {
  private readonly _actions: TActions;
  private readonly _transitions: Array<[string, string | null, TransitionCondition<any>?]>;

  constructor(
    actions: TActions = {} as TActions,
    transitions: Array<[string, string | null, TransitionCondition<any>?]> = []
  ) {
    this._actions = actions;
    this._transitions = transitions;
  }

  /**
   * Add actions to the graph builder.
   * Returns a new builder with accumulated action types.
   * 
   * @param actions - Record of action names to action instances
   * @throws Error if action names conflict with existing actions
   * 
   * @example
   * ```typescript
   * const builder = new GraphBuilder()
   *   .withActions({ action1, action2 })
   *   .withActions({ action3 });  // Accumulates types
   * ```
   */
  withActions<TNewActions extends Record<string, ActionLike<z.ZodObject<any>, z.ZodObject<any>, any, any>>>(
    actions: TNewActions
  ): GraphBuilder<TStateSchema, TActions & TNewActions> {
    // Validate: Check for duplicate action names
    const existingNames = Object.keys(this._actions);
    const newNames = Object.keys(actions);
    const duplicates = newNames.filter(name => existingNames.includes(name));
    
    if (duplicates.length > 0) {
      throw new Error(
        `Duplicate action names: ${duplicates.join(', ')}. ` +
        `Each action must have a unique name.`
      );
    }

    // Set action names from keys (immutable operation via withName())
    // If action already has the correct name, keep it (preserve reference)
    const actionsWithNames = Object.fromEntries(
      Object.entries(actions).map(([name, action]) => [
        name,
        action.name === name ? action : action.withName(name)
      ])
    ) as TNewActions;

    // Create new builder with merged actions (immutable)
    return new GraphBuilder<TStateSchema, TActions & TNewActions>(
      { ...this._actions, ...actionsWithNames } as TActions & TNewActions,
      [...this._transitions]
    );
  }

  /**
   * Add transitions between actions.
   * Transition conditions are typed based on the union of all action states.
   * 
   * @param transitions - Array of [from, to] or [from, to, condition] tuples
   * @throws Error if from/to action names don't exist
   * 
   * @example
   * ```typescript
   * builder.withTransitions(
   *   ['action1', 'action2'],
   *   ['action2', 'action3', (state) => state.count > 5],
   *   ['action3', null]  // Terminal transition
   * );
   * ```
   */
  withTransitions(
    ...transitions: Array<
      | [from: keyof TActions, to: keyof TActions | null]
      | [from: keyof TActions, to: keyof TActions | null, condition: TransitionCondition<InferStateType<TStateSchema, TActions>>]
    >
  ): this {
    const actionNames = Object.keys(this._actions);

    // Validate each transition
    for (const transition of transitions) {
      const [from, to] = transition;
      
      // Validate 'from' action exists
      if (!actionNames.includes(from as string)) {
        throw new Error(
          `Transition source '${String(from)}' not found in actions. ` +
          `Available actions: ${actionNames.join(', ')}`
        );
      }

      // Validate 'to' action exists (if not null)
      if (to !== null && !actionNames.includes(to as string)) {
        throw new Error(
          `Transition target '${String(to)}' not found in actions. ` +
          `Available actions: ${actionNames.join(', ')}`
        );
      }
    }

    // Create new builder with added transitions (immutable)
    // Need to cast to mutable temporarily to modify, then return as immutable
    const newTransitions = [...this._transitions, ...transitions] as Array<
      [string, string | null, TransitionCondition<any>?]
    >;

    // Return new instance with same actions but new transitions
    return new GraphBuilder<TStateSchema, TActions>(
      this._actions,
      newTransitions
    ) as this;
  }

  /**
   * Build the final graph.
   * Validates completeness and returns an immutable Graph instance.
   * The state schema type is computed as the union of all action reads/writes.
   * 
   * @throws Error if no actions have been added
   * @returns Immutable Graph instance with computed state schema type
   */
  build(): Graph<StateTypeToSchema<MergeActionStates<TActions>>> {
    // Validate: Must have at least one action
    const actionNames = Object.keys(this._actions);
    if (actionNames.length === 0) {
      throw new Error(
        'Cannot build graph with no actions. ' +
        'Add actions using withActions() before calling build().'
      );
    }

    // Convert transitions from tuples to Transition objects
    const transitions: Transition[] = this._transitions.map(([from, to, condition]) => ({
      from: from as string,
      to: to as string | null,
      condition
    }));

    return new Graph<StateTypeToSchema<MergeActionStates<TActions>>>(this._actions, transitions);
  }
}

