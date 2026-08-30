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
  description: "Multiple optional fields can be narrowed in single update"
};
// START_TEST
import { z } from 'zod';
import { State } from '../../../index';

const state = State.forAction(
  z.object({
    a: z.string().optional(),
    b: z.number().optional(),
    c: z.boolean().optional()
  }),
  z.object({
    a: z.string(),
    b: z.number(),
    c: z.boolean()
  }),
  {}
);

// All optional fields provided with concrete values
const updated = state.update({
  a: 'hello',
  b: 42,
  c: true
});

const a: string = updated.a;
const b: number = updated.b;
const c: boolean = updated.c;

