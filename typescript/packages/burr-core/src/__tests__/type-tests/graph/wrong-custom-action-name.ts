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
  type: "fail",
  errorCode: "TS2322",
  errorPattern: "not assignable",
  category: "graph",
  description: "Using variable name instead of custom key fails"
};
// START_TEST
import { z } from 'zod';
import { action, GraphBuilder } from '../../../index';

const myAction = action({
  reads: z.object({ count: z.number() }),
  writes: z.object({ count: z.number() }),
  update: ({ state }) => state.update({ count: state.count + 1 })
});

const builder = new GraphBuilder()
  .withActions({ customName: myAction });

// Error: 'myAction' is not a valid key, only 'customName' is
builder.withTransitions(['myAction', null]);

