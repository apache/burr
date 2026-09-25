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

// Core type definitions for Burr

import { z } from 'zod';

/**
 * Common interface for both Action and StreamingAction.
 * Used by Graph/GraphBuilder to accept either type.
 */
export interface ActionLike<
  TReadsSchema extends z.ZodObject<any> = z.ZodObject<any>,
  TWritesSchema extends z.ZodObject<any> = z.ZodObject<any>,
  TInputsSchema extends z.ZodType = z.ZodType,
  TResultSchema extends z.ZodObject<any> | z.ZodVoid = z.ZodObject<any> | z.ZodVoid
> {
  readonly name: string | undefined;
  readonly reads: readonly string[];
  readonly writes: readonly string[];
  readonly inputs: readonly string[];
  readonly schema: {
    readonly reads: TReadsSchema;
    readonly writes: TWritesSchema;
    readonly inputs: TInputsSchema;
    readonly result: TResultSchema;
  };
  withName(name: string): ActionLike<TReadsSchema, TWritesSchema, TInputsSchema, TResultSchema>;
}
