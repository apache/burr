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

// Public API exports for @apache-burr/core

// Re-export zod for convenience
export { z } from 'zod';

// State management
export {
  State,
  type StateInstance,
  createState,
  createStateWithDefaults,
  type Operation,
  type OperationConstructor,
  SetFieldsOperation,
  AppendFieldOperation,
  ExtendFieldOperation,
  IncrementFieldOperation,
  OperationRegistry,
  type NumberKeys,
  type ArrayKeys,
  type ArrayElement,
} from './state';

// Actions
export { Action, action as action } from './action';

// Types
export { type ActionLike } from './types';

// Graph
export { Graph, GraphBuilder, type Transition } from './graph';

// Application
export {
  Application,
  type StepResult,
  type RunResult,
  type ExecutionOptions
} from './application';
export { ApplicationBuilder } from './application-builder';

// Lifecycle hooks
export {
  type ExecuteMethod,
  type PreRunStepHook,
  type PostRunStepHook,
  type PostApplicationCreateHook,
  type PreStartSpanHook,
  type PostEndSpanHook,
  type DoLogAttributeHook,
  type PreExecuteCallHook,
  type PostExecuteCallHook,
  type PreStartStreamHook,
  type PostStreamItemHook,
  type PostEndStreamHook,
  type PreRunStepParams,
  type PostRunStepParams,
  type PostApplicationCreateParams,
  type PreStartSpanParams,
  type PostEndSpanParams,
  type DoLogAttributeParams,
  type PreExecuteCallParams,
  type PostExecuteCallParams,
  type PreStartStreamParams,
  type PostStreamItemParams,
  type PostEndStreamParams,
  type LifecycleAdapter,
  LifecycleAdapterSet,
} from './lifecycle';

// Serialization
export {
  serializeValue,
  deserializeValue,
  serializeState,
  deserializeState,
  type Serializer,
  type Deserializer,
  type SerdeOptions,
} from './serde';

// Persistence
export {
  type PersistedStateData,
  type StateLoader,
  type StateSaver,
  type StatePersister,
  PersisterHook,
  InMemoryPersister,
} from './persistence';

// Streaming
export {
  StreamingAction,
  streamingAction,
  StreamingResultContainer,
  isStreamingAction,
} from './streaming';

// Tracing & observability
export {
  ActionSpan,
  ActionSpanTracer,
  TracerFactory,
  getCurrentTracer,
  runWithTracer,
  trace,
} from './tracing';

// Parallelism & sub-graphs
export {
  RunnableGraph,
  SubGraphTask,
  TaskBasedParallelAction,
  MapActionsAndStates,
  MapActions,
  MapStates,
  type ApplicationContext,
  type CascadeBehavior,
} from './parallelism';

