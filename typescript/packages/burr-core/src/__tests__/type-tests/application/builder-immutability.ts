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
  category: "application",
  description: "Method chaining is immutable - each call returns new instance"
};
// START_TEST
import { z } from 'zod';
import { action, GraphBuilder, ApplicationBuilder, createState } from '../../../index';

const action1 = action({
  reads: z.object({ x: z.number() }),
  writes: z.object({ y: z.number() }),
  update: ({ state }) => state.update({ y: state.x })
});

const graph = new GraphBuilder()
  .withActions({ action1 })
  .build();

const state = createState(
  z.object({ x: z.number(), y: z.number() }),
  { x: 5, y: 0 }
);

const builder1 = new ApplicationBuilder();
const builder2 = builder1.withGraph(graph);
const builder3 = builder2.withEntrypoint('action1');
const builder4 = builder3.withState(state);

// Each builder is a different instance
const _b1 = builder1;
const _b2 = builder2;
const _b3 = builder3;
const _b4 = builder4;

