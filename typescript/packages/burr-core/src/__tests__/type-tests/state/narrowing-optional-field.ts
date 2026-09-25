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
  description: "Updating optional field with concrete value narrows type"
};
// START_TEST
import { z } from 'zod';
import { State } from '../../../index';

const state = State.forAction(
  z.object({ 
    count: z.number(),
    history: z.array(z.string()).optional()  // Optional
  }),
  z.object({ 
    count: z.number(),
    history: z.array(z.string())  // Required in writes
  }),
  { count: 0 }
);

const updated = state.update({ 
  count: 1,
  history: ['item1', 'item2']
});

const count: number = updated.count;
const history: string[] = updated.history;

