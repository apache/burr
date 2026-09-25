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

// State persistence interfaces and implementations
//
// Mirrors Python's burr/core/persistence.py.
// All interfaces are async-only (TS port is async throughout).

import { type PostRunStepHook, type PostRunStepParams } from './lifecycle';
import { serializeState, type SerdeOptions } from './serde';

// ============================================================================
// Data Types
// ============================================================================

/**
 * Persisted state record.
 * Mirrors Python's PersistedStateData TypedDict.
 */
export interface PersistedStateData {
  partitionKey: string;
  appId: string;
  sequenceId: number;
  /** Name of the action that produced this state */
  position: string;
  /** Serialized state data */
  state: Record<string, any>;
  /** ISO timestamp */
  createdAt: string;
  /** 'completed' after successful action, 'failed' if action threw */
  status: 'completed' | 'failed';
}

// ============================================================================
// Interfaces
// ============================================================================

/**
 * Loads persisted state.
 * Mirrors Python's BaseStateLoader / AsyncBaseStateLoader.
 */
export interface StateLoader {
  /**
   * Load state for a given app_id.
   *
   * @param partitionKey - Partition key for this application group
   * @param appId - The specific application instance ID (null to get latest)
   * @param sequenceId - Optional: load state at a specific point in time.
   *   If not provided, returns the latest completed state.
   * @returns Persisted state data, or null if not found
   */
  load(
    partitionKey: string,
    appId: string | null,
    sequenceId?: number
  ): Promise<PersistedStateData | null>;

  /**
   * List all app IDs for a given partition key.
   */
  listAppIds(partitionKey: string): Promise<string[]>;
}

/**
 * Saves state to persistent storage.
 * Mirrors Python's BaseStateSaver / AsyncBaseStateSaver.
 */
export interface StateSaver {
  /**
   * One-time initialization (e.g., create tables, connect to database).
   */
  initialize(): Promise<void>;

  /**
   * Save state checkpoint.
   *
   * Unique key: (partitionKey, appId, sequenceId, position)
   */
  save(params: {
    partitionKey: string | undefined;
    appId: string;
    sequenceId: number;
    position: string;
    state: Record<string, any>;
    status: 'completed' | 'failed';
  }): Promise<void>;
}

/**
 * Combined loader + saver interface.
 */
export interface StatePersister extends StateLoader, StateSaver {}

// ============================================================================
// PersisterHook
// ============================================================================

/**
 * Wraps a StateSaver as a PostRunStepHook.
 *
 * This mirrors the Python pattern where persistence is wired as a lifecycle hook.
 * After each step, the hook serializes and saves the state.
 */
export class PersisterHook implements PostRunStepHook {
  private readonly _saver: StateSaver;
  private readonly _serdeOptions?: SerdeOptions;

  constructor(saver: StateSaver, serdeOptions?: SerdeOptions) {
    this._saver = saver;
    this._serdeOptions = serdeOptions;
  }

  async postRunStep(params: PostRunStepParams): Promise<void> {
    const status = params.exception ? 'failed' : 'completed';
    const serialized = serializeState(params.state.data, this._serdeOptions);

    await this._saver.save({
      partitionKey: params.partitionKey ?? '',
      appId: params.appId,
      sequenceId: params.sequenceId,
      position: params.action.name ?? 'unknown',
      state: serialized,
      status,
    });
  }
}

// ============================================================================
// InMemoryPersister
// ============================================================================

/**
 * In-memory state persister for testing.
 * Not suitable for production use (no durability).
 */
export class InMemoryPersister implements StatePersister {
  private _records: PersistedStateData[] = [];
  private _initialized = false;

  async initialize(): Promise<void> {
    this._initialized = true;
  }

  get isInitialized(): boolean {
    return this._initialized;
  }

  async save(params: {
    partitionKey: string | undefined;
    appId: string;
    sequenceId: number;
    position: string;
    state: Record<string, any>;
    status: 'completed' | 'failed';
  }): Promise<void> {
    this._records.push({
      partitionKey: params.partitionKey ?? '',
      appId: params.appId,
      sequenceId: params.sequenceId,
      position: params.position,
      state: params.state,
      createdAt: new Date().toISOString(),
      status: params.status,
    });
  }

  async load(
    partitionKey: string,
    appId: string | null,
    sequenceId?: number
  ): Promise<PersistedStateData | null> {
    let candidates = this._records.filter(
      (r) => r.partitionKey === partitionKey && r.status === 'completed'
    );

    if (appId !== null) {
      candidates = candidates.filter((r) => r.appId === appId);
    }

    if (sequenceId !== undefined) {
      candidates = candidates.filter((r) => r.sequenceId === sequenceId);
    }

    if (candidates.length === 0) return null;

    // Return the one with highest sequenceId
    return candidates.reduce((latest, current) =>
      current.sequenceId > latest.sequenceId ? current : latest
    );
  }

  async listAppIds(partitionKey: string): Promise<string[]> {
    const ids = new Set(
      this._records
        .filter((r) => r.partitionKey === partitionKey)
        .map((r) => r.appId)
    );
    return [...ids];
  }

  /** Test helper: get all records */
  get records(): readonly PersistedStateData[] {
    return this._records;
  }

  /** Test helper: clear all records */
  clear(): void {
    this._records = [];
  }
}
