// Licensed to the Apache Software Foundation (ASF) under one
// or more contributor license agreements.  See the NOTICE file
// distributed with this work for additional information
// regarding copyright ownership.  The ASF licenses this file
// to you under the Apache License, Version 2.0 (the
// "License"); you may not use this file except in compliance
// with the License.  You may obtain a copy of the License at
//
//   http://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing,
// software distributed under the License is distributed on an
// "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
// KIND, either express or implied.  See the License for the
// specific language governing permissions and limitations
// under the License.

export const TEST_META = {
  type: "pass",
  category: "state",
  description: "Chained updates preserve narrow literal types"
};
// START_TEST
import { z } from 'zod';
import { State } from '../../../index';

const state = State.forAction(
  z.object({ a: z.string() }),
  z.object({ b: z.number(), c: z.boolean() }),
  { a: 'test' }
);

const updated = state.update({ b: 42 }).update({ c: true });

// Each update should narrow: { a: string } & { b: 42 } & { c: true }
// NOT: { a: string } & Partial<{ b: number, c: boolean }>
const a: string = updated.data.a;
const b: 42 = updated.data.b;
const c: true = updated.data.c;

