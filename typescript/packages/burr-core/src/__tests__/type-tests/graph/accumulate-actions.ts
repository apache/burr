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
  category: "graph",
  description: "Actions accumulate across multiple withActions calls"
};
// START_TEST
import { z } from 'zod';
import { action, GraphBuilder } from '../../../index';

const action1 = action({
  reads: z.object({ x: z.number() }),
  writes: z.object({ y: z.number() }),
  update: ({ state }) => state.update({ y: state.x })
});

const action2 = action({
  reads: z.object({ y: z.number() }),
  writes: z.object({ z: z.number() }),
  update: ({ state }) => state.update({ z: state.y })
});

const builder = new GraphBuilder()
  .withActions({ action1 })
  .withActions({ action2 });

// Both action1 and action2 should be valid
builder.withTransitions(
  ['action1', 'action2'],
  ['action2', null]
);

