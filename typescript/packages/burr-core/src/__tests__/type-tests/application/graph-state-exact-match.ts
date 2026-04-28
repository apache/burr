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
  description: "withGraph then withState with exact match should pass"
};
// START_TEST
import { z } from 'zod';
import { action, GraphBuilder, ApplicationBuilder, createState } from '../../../index';

const counter = action({
  reads: z.object({ counter: z.number() }),
  writes: z.object({ counter: z.number() }),
  update: ({ state }) => state.update({ counter: state.counter + 1 })
});

const graph = new GraphBuilder()
  .withActions({ counter })
  .build();

const app = new ApplicationBuilder()
  .withGraph(graph)
  .withEntrypoint('counter')
  .withState(createState(
    z.object({ counter: z.number() }),
    { counter: 0 }
  ));

const _unused = app;

