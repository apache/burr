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
  description: "Increment compiles (excess property checking is runtime via Zod)"
};
// START_TEST
import { z } from 'zod';
import { State } from '../../../index';

const state = State.forAction(
  z.object({ count: z.number(), score: z.number() }),
  z.object({ count: z.number() }),
  { count: 0, score: 0 }
);

// Excess property checking is validated at runtime by Zod
const result = state.increment({ count: 1 });
const count: number = result.count;

