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
  errorCode: "TS2769",
  errorPattern: "not assignable",
  category: "state",
  description: "Type mismatch in update shows clear error"
};
// START_TEST
import { z } from 'zod';
import { action } from '../../../index';

action({
  reads: z.object({ a: z.string() }),
  writes: z.object({ b: z.boolean() }),
  update: ({ state }) => state.update({ b: 'wrong_type' })
});

