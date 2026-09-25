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
  description: "Increment accepts multiple number fields"
};
// START_TEST
import { z } from 'zod';
import { createState } from '../../../index';

const state = createState(
  z.object({ count: z.number(), score: z.number(), lives: z.number() }), 
  { count: 0, score: 0, lives: 3 }
);

const result = state.increment({ count: 1, score: 10, lives: -1 });
const count: number = result.count;
const score: number = result.score;
const lives: number = result.lives;

