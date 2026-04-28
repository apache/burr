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

/**
 * Hello World Counter — TypeScript port of examples/hello-world-counter/application.py
 *
 * Demonstrates:
 *   - Defining actions with Zod schemas
 *   - Building a graph with conditional transitions
 *   - Running an application to completion
 *   - Persistence with InMemoryPersister (rebuild & resume)
 *   - Stepping through execution one action at a time
 *
 * Run:  npx ts-node scratch-examples/hello-world-counter.ts
 *   or: npx jest --testPathPattern integration  (for the test version)
 */

import { z } from 'zod';
import { action, createState, GraphBuilder, ApplicationBuilder } from '../src';
import { InMemoryPersister } from '../src/persistence';

// ============================================================================
// 1. Define actions
// ============================================================================

const counter = action({
  reads: z.object({ counter: z.number() }),
  writes: z.object({ counter: z.number() }),
  update: ({ state }) => {
    const next = state.counter + 1;
    console.log(`  counted to ${next}`);
    return state.update({ counter: next });
  },
});

// ============================================================================
// 2. Build graph with conditional loop
// ============================================================================

const COUNT_UP_TO = 10;

const graph = new GraphBuilder()
  .withActions({ counter })
  .withTransitions(
    ['counter', 'counter', (s: any) => s.counter < COUNT_UP_TO],
    ['counter', null],  // terminal when condition is false
  )
  .build();

// ============================================================================
// 3. Run to completion
// ============================================================================

async function runToCompletion() {
  console.log(`\n=== Run to completion (counting to ${COUNT_UP_TO}) ===\n`);

  const app = new ApplicationBuilder()
    .withGraph(graph)
    .withEntrypoint('counter')
    .withState(createState(z.object({ counter: z.number() }), { counter: 0 }))
    .withIdentifiers('counter-run')
    .build();

  const result = await app.run();
  console.log(`\n  Final counter: ${result.state.data.counter}`);
}

// ============================================================================
// 4. Step-by-step with persistence and rebuild
// ============================================================================

async function stepWithPersistence() {
  console.log(`\n=== Step-by-step with rebuild from persistence ===\n`);

  const persister = new InMemoryPersister();
  await persister.initialize();

  const appId = 'counter-step';
  const partitionKey = 'demo-user';
  const defaultState = createState(z.object({ counter: z.number() }), { counter: 0 });

  let stepCount = 0;
  while (true) {
    // Rebuild app from persistence each time (simulates server restart)
    const builder = await new ApplicationBuilder()
      .withGraph(graph)
      .withStatePersister(persister)
      .initializeFrom({
        loader: persister,
        partitionKey,
        appId,
        defaultState,
        defaultEntrypoint: 'counter',
        resumeAtNextAction: true,
      });

    const app = builder.build();

    const step = await app.step();
    if (!step) {
      console.log(`\n  Reached terminal state after ${stepCount} steps`);
      break;
    }
    stepCount++;
  }

  // Verify final persisted state
  const final = await persister.load(partitionKey, appId);
  console.log(`  Persisted records: ${persister.records.length}`);
  console.log(`  Final persisted counter: ${final?.state?.counter ?? 'N/A'}`);
}

// ============================================================================
// 5. Iterate (async generator)
// ============================================================================

async function iterateDemo() {
  console.log(`\n=== Iterate (async generator) ===\n`);

  const app = new ApplicationBuilder()
    .withGraph(graph)
    .withEntrypoint('counter')
    .withState(createState(z.object({ counter: z.number() }), { counter: 0 }))
    .withIdentifiers('counter-iterate')
    .build();

  for await (const _step of app.iterate()) {
    // action prints each count; iterate lets us observe each step
  }

  console.log(`  Final counter: ${app.state.data.counter}`);
}

// ============================================================================
// Main
// ============================================================================

async function main() {
  console.log('Hello World Counter — @apache-burr/core TypeScript');
  console.log('='.repeat(50));

  await runToCompletion();
  await stepWithPersistence();
  await iterateDemo();

  console.log('\n✓ All demos completed successfully.\n');
}

main().catch((err) => {
  console.error('FAILED:', err);
  process.exit(1);
});
