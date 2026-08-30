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
  description: "Update compiles (excess property checking is runtime via Zod)"
};
// START_TEST
import { z } from 'zod';
import { State } from '../../../index';

const state = State.forAction(
  z.object({ a: z.number() }),
  z.object({ a: z.number() }),
  { a: 1 }
);

// Excess property checking is validated at runtime by Zod
// TypeScript's structural typing makes compile-time excess property checking complex
const result = state.update({ a: 2 });
const a: number = result.a;

