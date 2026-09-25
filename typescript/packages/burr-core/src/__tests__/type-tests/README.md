# Type Tests

Tests that verify compile-time type safety using TypeScript's compiler API.

## Running Tests

```bash
npm run test:types
```

## Writing a Test

Create a `.ts` file in the appropriate category directory (`actions/`, `state/`, `graph/`, etc.):

```typescript
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
  type: "fail",                    // "pass" or "fail"
  errorCode: "TS2769",             // Required for "fail" tests
  errorPattern: "Property 'z' is missing",  // Substring to match
  category: "actions",
  description: "Action must write all fields"
};
// START_TEST
import { z } from 'zod';
import { action } from '../../../index';

const bad = action({
  writes: z.object({ y: z.number(), z: z.number() }),
  update: ({ state }) => state.update({ y: 1 })  // Missing 'z'
});
```

**Important:** Everything before `// START_TEST` is metadata. Everything after is compiled and type-checked.

**Pass tests** should compile without errors.

**Fail tests** must specify:
- `errorCode`: TypeScript error code (e.g. "TS2769")
- `errorPattern`: Substring that must appear in error message

## Test Organization

Tests are organized by subject area, not pass/fail:
- `actions/` - Action definitions, reads/writes validation
- `state/` - State mutations, type narrowing, restrictions
- `graph/` - Graph builder, transitions
- `application/` - Application builder API

File names should be descriptive (e.g. `missing-writes.ts`, not `test1.ts`).

## How It Works

1. Framework discovers all `.ts` files in this directory
2. Parses `TEST_META` to get expectations
3. Compiles code after `// START_TEST` using TypeScript Compiler API
4. Validates diagnostics match expectations
5. Reports results as Jest tests

Tests run in parallel for speed (~2-3s for all tests).

