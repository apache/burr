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
  description: "GraphBuilder accepts valid actions and transitions"
};
// START_TEST
import { z } from 'zod';
import { action, GraphBuilder } from '../../../index';

// This should pass: valid graph with two actions
const action1 = action({
  reads: z.object({ x: z.number() }),
  writes: z.object({ y: z.string() }),
  update: ({ state }) => state.update({ y: 'test' })
});

const action2 = action({
  reads: z.object({ y: z.string() }),
  writes: z.object({ z: z.boolean() }),
  update: ({ state }) => state.update({ z: true })
});

const graph = new GraphBuilder()
  .withActions({ action1, action2 })
  .withTransitions(['action1', 'action2'], ['action2', null])
  .build();

