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
 * E2E Execution Tests
 * 
 * Contract tests for Application execution engine:
 * - app.step() - Single step execution
 * - app.run() - Run to completion
 * - app.iterate() - Iterator pattern
 * - State management
 * - Graph transitions
 */

import { z } from 'zod';
import { action, createState, GraphBuilder, ApplicationBuilder } from '../index';

// ============================================================================
// Test Fixtures
// ============================================================================

const counter = action({
  reads: z.object({ count: z.number() }),
  writes: z.object({ count: z.number() }),
  update: ({ state }) => state.update({ count: state.count + 1 })
});

const counterWithInputs = action({
  reads: z.object({ count: z.number() }),
  writes: z.object({ count: z.number() }),
  inputs: z.object({ additional: z.number() }),
  update: ({ state, inputs }) => state.update({ 
    count: state.count + 1 + inputs.additional 
  })
});

const result = action({
  reads: z.object({ count: z.number() }),
  writes: z.object({}),
  result: z.object({ value: z.number() }),
  run: async ({ state }) => ({ value: state.count }),
  // @ts-expect-error - Empty writes is valid for read-only actions
  update: ({ state }) => state
});


// ============================================================================
// Core Execution - app.step()
// ============================================================================

describe('app.step() - Basic Execution', () => {
  // Tests basic single step execution with simple self-looping graph.
  // Create graph with one action + self-loop transition, execute step, verify state incremented and next action returned.
  test('executes single action and advances state', async () => {
    const graph = new GraphBuilder()
      .withActions({ counter })
      .withTransitions(['counter', 'counter'])
      .build();

    const app = new ApplicationBuilder()
      .withGraph(graph)
      .withState(createState(z.object({ count: z.number() }), { count: 0 }))
      .withEntrypoint('counter')
      .build();

    const result = await app.step();

    expect(result).not.toBeNull();
    expect(result!.state.count).toBe(1);
  });

  // Tests that step() correctly passes runtime inputs to actions requiring them.
  // Create graph with input-requiring action, call step() with inputs object, verify inputs used in state computation.
  test('passes inputs to action', async () => {
    const graph = new GraphBuilder()
      .withActions({ counterWithInputs })
      .withTransitions(['counterWithInputs', 'counterWithInputs'])
      .build();

    const app = new ApplicationBuilder()
      .withGraph(graph)
      .withState(createState(z.object({ count: z.number() }), { count: 0 }))
      .withEntrypoint('counterWithInputs')
      .build();

    const result = await app.step({ inputs: { additional: 5 } });

    expect(result).not.toBeNull();
    expect(result!.state.count).toBe(6);  // 0 + 1 + 5
  });

  // Tests terminal state detection when action has no outgoing transitions.
  // Create graph with no transitions from entrypoint, execute two steps, second step returns null at terminal.
  test('returns null when no next actions', async () => {
    const graph = new GraphBuilder()
      .withActions({ counter })
      .build();  // No transitions = terminal

    const app = new ApplicationBuilder()
      .withGraph(graph)
      .withState(createState(z.object({ count: z.number() }), { count: 0 }))
      .withEntrypoint('counter')
      .build();

    await app.step();  // First step succeeds
    const result = await app.step();  // Second step hits terminal

    expect(result).toBeNull();
  });

  // Tests that errors thrown during action execution propagate to caller.
  // Create action that throws error in run(), execute step, expect error to bubble up with action context.
  test('action errors bubble up', async () => {
    const brokenAction = action({
      reads: z.object({}),
      writes: z.object({}),
      run: async () => {
        throw new Error('Action failed!');
      },
      update: ({ state }) => state
    });

    const graph = new GraphBuilder()
      .withActions({ brokenAction })
      .build();  // No transitions = terminal

    const app = new ApplicationBuilder()
      .withGraph(graph)
      .withState(createState(z.object({}), {}))
      .withEntrypoint('brokenAction')
      .build();

    await expect(app.step()).rejects.toThrow('Action failed!');
  });
});

// ============================================================================
// Core Execution - app.run()
// ============================================================================

describe('app.run() - Run to Completion', () => {
  // Tests run() executes steps until reaching action with no outgoing transitions.
  // Create graph with conditional loop and terminal action, call run(), verify final state after all steps executed.
  test('runs until terminal state', async () => {
    const graph = new GraphBuilder()
      .withActions({ counter, result })
      .withTransitions(
        ['counter', 'counter', (state) => state.count < 10],
        ['counter', 'result']
        // result has no outgoing transition = terminal
      )
      .build();

    const app = new ApplicationBuilder()
      .withGraph(graph)
      .withState(createState(z.object({ count: z.number() }), { count: 0 }))
      .withEntrypoint('counter')
      .build();

    const final = await app.run();

    expect(final.state.count).toBe(10);
    expect(final.result).toHaveProperty('value', 10);
  });

  // Tests haltAfter stops execution immediately after specified action completes.
  // Run with haltAfter targeting terminal action, verify action executed and result captured before stopping.
  test('stops after executing specified action', async () => {
    const graph = new GraphBuilder()
      .withActions({ counter, result })
      .withTransitions(
        ['counter', 'counter', (state) => state.count < 10],
        ['counter', 'result']
        // result has no outgoing transition = terminal
      )
      .build();

    const app = new ApplicationBuilder()
      .withGraph(graph)
      .withState(createState(z.object({ count: z.number() }), { count: 0 }))
      .withEntrypoint('counter')
      .build();

    const final = await app.run({ haltAfter: ['result'] });

    expect(final.state.count).toBe(10);
    expect(final.result).toHaveProperty('value', 10);
  });

  // Tests haltBefore stops execution before specified action runs.
  // Run with haltBefore targeting specific action, verify execution stops without running that action (result is null).
  test('stops before executing specified action', async () => {
    const graph = new GraphBuilder()
      .withActions({ counter, result })
      .withTransitions(
        ['counter', 'counter', (state) => state.count < 10],
        ['counter', 'result']
        // result has no outgoing transition = terminal
      )
      .build();

    const app = new ApplicationBuilder()
      .withGraph(graph)
      .withState(createState(z.object({ count: z.number() }), { count: 0 }))
      .withEntrypoint('counter')
      .build();

    const final = await app.run({ haltBefore: ['result'] });

    expect(final.state.count).toBe(10);
    expect(final.result).toBeNull();  // Didn't execute result (halted before)
  });

  // Tests that inputs passed to run() are available to all actions throughout execution.
  // Run with global inputs, verify each action in sequence receives and uses the inputs in computation.
  test('global inputs available to all actions', async () => {
    const graph = new GraphBuilder()
      .withActions({ counterWithInputs, result })
      .withTransitions(
        ['counterWithInputs', 'counterWithInputs', (state) => state.count < 10],
        ['counterWithInputs', 'result']
        // result has no outgoing transition = terminal
      )
      .build();

    const app = new ApplicationBuilder()
      .withGraph(graph)
      .withState(createState(z.object({ count: z.number() }), { count: 0 }))
      .withEntrypoint('counterWithInputs')
      .build();

    const final = await app.run({ inputs: { additional: 4 }, haltAfter: ['result'] });

    // Each step: count + 1 + 4 = count + 5
    // Step 1: 0 + 5 = 5
    // Step 2: 5 + 5 = 10
    expect(final.state.count).toBe(10);
  });

});

// ============================================================================
// Core Execution - app.iterate()
// ============================================================================

describe('app.iterate() - Iterator Pattern', () => {
  // Tests iterate() async generator yields each step result until terminal state.
  // Create graph that loops N times then terminates, iterate collecting all steps, verify total count matches expected.
  test('yields each step until completion', async () => {
    const graph = new GraphBuilder()
      .withActions({ counter, result })
      .withTransitions(
        ['counter', 'counter', (state) => state.count < 5],
        ['counter', 'result']
        // result has no outgoing transition = terminal
      )
      .build();

    const app = new ApplicationBuilder()
      .withGraph(graph)
      .withState(createState(z.object({ count: z.number() }), { count: 0 }))
      .withEntrypoint('counter')
      .build();

    let stepCount = 0;
    for await (const _step of app.iterate()) {
      stepCount++;
    }

    // counter runs 5 times (0→1→2→3→4→5), then result = 6 total steps
    expect(stepCount).toBe(6);
  });

  // Tests that user can manually break from iterate() loop before completion.
  // Create infinite loop graph, iterate with conditional break statement, verify execution stopped early at correct count.
  test('user can break out of iteration', async () => {
    const graph = new GraphBuilder()
      .withActions({ counter })
      .withTransitions(['counter', 'counter'])
      .build();

    const app = new ApplicationBuilder()
      .withGraph(graph)
      .withState(createState(z.object({ count: z.number() }), { count: 0 }))
      .withEntrypoint('counter')
      .build();

    let stepCount = 0;
    for await (const step of app.iterate()) {
      stepCount++;
      if (step.state.count === 5) {
        break;  // User-controlled break
      }
    }

    expect(stepCount).toBe(5);
  });
});

// ============================================================================
// Graph & Transitions
// ============================================================================

describe('Graph & Transitions', () => {
  // Tests that transition conditions are evaluated in declaration order and first match is taken.
  // Create graph with multiple overlapping conditional transitions, execute with different states, verify correct transition selected based on order.
  test('transitions_evaluated_in_order: first match wins', async () => {
    const low = action({
      reads: z.object({ count: z.number() }),
      writes: z.object({ level: z.string() }),
      update: ({ state }) => state.update({ level: 'low' })
    });
    const high = action({
      reads: z.object({ count: z.number() }),
      writes: z.object({ level: z.string() }),
      update: ({ state }) => state.update({ level: 'high' })
    });

    const graph = new GraphBuilder()
      .withActions({ counter, low, high })
      .withTransitions(
        ['counter', 'low', (state) => state.count < 5],   // Check first
        ['counter', 'high', (state) => state.count >= 5]  // Check second
        // low and high have no outgoing transitions = terminal
      )
      .build();

    const app1 = new ApplicationBuilder()
      .withGraph(graph)
      .withState(createState(
        z.object({ count: z.number(), level: z.string().optional() }),
        { count: 0, level: "hello" }
      ))
      .withEntrypoint('counter')
      .build();

    const result1 = await app1.step();
    expect(result1).not.toBeNull();
    // First transition matches (count < 5), will go to 'low' on next step

    const app2 = new ApplicationBuilder()
      .withGraph(graph)
      .withState(createState(
        z.object({ count: z.number(), level: z.string().optional() }),
        { count: 5 }
      ))
      .withEntrypoint('counter')
      .build();

    const result2 = await app2.step();
    expect(result2).not.toBeNull();
    // First transition fails (count >= 5), second matches, will go to 'high' on next step
  });

  // Tests that transition conditions evaluate using state after action execution.
  // Create graph with conditional loop checking counter, run to completion, verify condition controlled flow using updated state.
  test('transitions_conditional: conditions evaluate on current state', async () => {
    const setLevel = action({
      reads: z.object({ count: z.number() }),
      writes: z.object({ level: z.string() }),
      update: ({ state }) => state.update({ 
        level: state.count < 5 ? 'low' : 'high' 
      })
    });

    const graph = new GraphBuilder()
      .withActions({ counter, setLevel })
      .withTransitions(
        ['counter', 'counter', (state) => state.count! < 10],
        ['counter', 'setLevel']
        // setLevel has no outgoing transition = terminal
      )
      .build();

    const app = new ApplicationBuilder()
      .withGraph(graph)
      .withState(createState(
        z.object({ count: z.number(), level: z.string().optional() }),
        { count: 0 }
      ))
      .withEntrypoint('counter')
      .build();

    const result = await app.run();

    expect(result.state.count).toBe(10);
    expect(result.state.level).toBe('high');  // 10 >= 5
  });

});

// ============================================================================
// Integration Scenarios
// ============================================================================

describe('Integration Scenarios', () => {
  // Tests multi-step execution sequence with state evolution through multiple actions.
  // Execute multiple manual steps through conditional loop then terminal action, verify state progression at each step.
  test('multi_action_sequence: counter → result → terminal', async () => {
    const graph = new GraphBuilder()
      .withActions({ counter, result })
      .withTransitions(
        ['counter', 'counter', (state) => state.count < 3],
        ['counter', 'result']
        // result has no outgoing transition = terminal
      )
      .build();

    const app = new ApplicationBuilder()
      .withGraph(graph)
      .withState(createState(z.object({ count: z.number() }), { count: 0 }))
      .withEntrypoint('counter')
      .build();

    // Step 1: counter (0 → 1)
    const step1 = await app.step();
    expect(step1?.state.count).toBe(1);

    // Step 2: counter (1 → 2)
    const step2 = await app.step();
    expect(step2?.state.count).toBe(2);

    // Step 3: counter (2 → 3)
    const step3 = await app.step();
    expect(step3?.state.count).toBe(3);

    // Step 4: result (extracts count)
    const step4 = await app.step();
    expect(step4?.result).toHaveProperty('value', 3);

    // Step 5: terminal
    const step5 = await app.step();
    expect(step5).toBeNull();
  });

  // Tests that actions with separate run/update phases execute both correctly.
  // Create action with both run() producing result and update() using result, execute step, verify both run output and state update applied.
  test('action_with_result: run/update phases work correctly', async () => {
    const multiPhase = action({
      reads: z.object({ input: z.string() }),
      writes: z.object({ output: z.string() }),
      result: z.object({ processed: z.string() }),
      run: async ({ state }) => ({ 
        processed: state.input.toUpperCase() 
      }),
      update: ({ state, result }) => state.update({ 
        output: result.processed 
      })
    });

    const graph = new GraphBuilder()
      .withActions({ multiPhase })
      .build();  // No transitions = terminal

    const app = new ApplicationBuilder()
      .withGraph(graph)
      .withState(createState(
        z.object({ input: z.string(), output: z.string().optional() }), 
        { input: 'hello' }
      ))
      .withEntrypoint('multiPhase')
      .build();

    const result = await app.step();

    expect(result).not.toBeNull();
    expect(result!.result).toHaveProperty('processed', 'HELLO');  // run() output
    expect(result!.state.output).toBe('HELLO');                    // update() applied it
  });
});

// ============================================================================
// Critical Production Tests
// ============================================================================

describe('Critical Production Tests', () => {
  // Tests that sequence ID correctly increments with each step execution.
  // Verifies internal execution tracking is maintained across multiple steps for replay/debugging.
  test('sequence ID increments correctly across multiple steps', async () => {
    const graph = new GraphBuilder()
      .withActions({ counter })
      .withTransitions(['counter', 'counter'])
      .build();

    const app = new ApplicationBuilder()
      .withGraph(graph)
      .withState(createState(z.object({ count: z.number() }), { count: 0 }))
      .withEntrypoint('counter')
      .withIdentifiers('test-app')
      .build();

    // Initial sequence ID should be 0
    expect(app.state.data.executionMetadata.sequenceId).toBe(0);

    // Verify sequence ID increments with each step
    for (let i = 1; i <= 3; i++) {
      await app.step();
      expect(app.state.data.executionMetadata.sequenceId).toBe(i);
    }
  });

  // Tests that framework metadata (appMetadata and executionMetadata) persists correctly during run().
  // Verifies metadata doesn't get lost during state merges throughout entire execution lifecycle.
  test('framework metadata persists correctly through run()', async () => {
    const graph = new GraphBuilder()
      .withActions({ counter, result })
      .withTransitions(
        ['counter', 'counter', (state) => state.count < 5],
        ['counter', 'result']
      )
      .build();

    const app = new ApplicationBuilder()
      .withGraph(graph)
      .withState(createState(z.object({ count: z.number() }), { count: 0 }))
      .withEntrypoint('counter')
      .withIdentifiers('my-app', 'partition-123')
      .build();

    const final = await app.run();

    // App metadata should be unchanged
    expect(final.state.data.appMetadata).toEqual({
      appId: 'my-app',
      partitionKey: 'partition-123',
      entrypoint: 'counter'
    });

    // Execution metadata should be updated
    expect(final.state.data.executionMetadata.sequenceId).toBeGreaterThan(0);
    expect(final.state.data.executionMetadata.priorStep).toBe('result');
  });

  // Tests that actions cannot declare writes to reserved framework metadata keys.
  // Verifies defense-in-depth validation prevents metadata corruption.
  test('actions cannot write to framework metadata', async () => {
    const maliciousAction = action({
      reads: z.object({ count: z.number() }),
      // Malicious action declares it will write to metadata
      writes: z.object({ count: z.number(), appMetadata: z.any() }),
      update: ({ state }) => {
        // Try to write to both count and metadata
        return state.update({ 
          count: state.count + 1,
          appMetadata: { appId: 'hacked' }
        } as any);
      }
    });

    const graph = new GraphBuilder()
      .withActions({ maliciousAction })
      .build();

    const app = new ApplicationBuilder()
      .withGraph(graph)
      .withState(createState(z.object({ count: z.number() }), { count: 0 }))
      .withEntrypoint('maliciousAction')
      .withIdentifiers('test-app')
      .build();

    // Should throw during COMMIT phase when validating write keys
    await expect(app.step()).rejects.toThrow(/reserved metadata keys/i);
  });

  // Tests complex graph with multiple conditional branches (3+ outgoing transitions).
  // Verifies transition evaluation order and correct path selection in realistic decision trees.
  test('complex branching with multiple transitions works correctly', async () => {
    const low = action({
      reads: z.object({ count: z.number() }),
      writes: z.object({ level: z.string() }),
      update: ({ state }) => state.update({ level: 'low' })
    });
    
    const medium = action({
      reads: z.object({ count: z.number() }),
      writes: z.object({ level: z.string() }),
      update: ({ state }) => state.update({ level: 'medium' })
    });
    
    const high = action({
      reads: z.object({ count: z.number() }),
      writes: z.object({ level: z.string() }),
      update: ({ state }) => state.update({ level: 'high' })
    });

    const graph = new GraphBuilder()
      .withActions({ counter, low, medium, high })
      .withTransitions(
        ['counter', 'low', (state) => state.count < 3],     // Priority 1
        ['counter', 'medium', (state) => state.count < 7],   // Priority 2
        ['counter', 'high', (state) => state.count >= 7]     // Priority 3
      )
      .build();

    // Test low path
    const app1 = new ApplicationBuilder()
      .withGraph(graph)
      .withState(createState(
        z.object({ count: z.number(), level: z.string().optional() }), 
        { count: 1 }
      ))
      .withEntrypoint('counter')
      .build();
    
    await app1.step(); // counter: 1 → 2
    const step2 = await app1.step(); // should go to 'low'
    expect(step2?.action.name).toBe('low');

    // Test medium path
    const app2 = new ApplicationBuilder()
      .withGraph(graph)
      .withState(createState(
        z.object({ count: z.number(), level: z.string().optional() }), 
        { count: 5 }
      ))
      .withEntrypoint('counter')
      .build();
    
    await app2.step(); // counter: 5 → 6
    const step2b = await app2.step(); // should go to 'medium'
    expect(step2b?.action.name).toBe('medium');

    // Test high path
    const app3 = new ApplicationBuilder()
      .withGraph(graph)
      .withState(createState(
        z.object({ count: z.number(), level: z.string().optional() }), 
        { count: 7 }
      ))
      .withEntrypoint('counter')
      .build();
    
    await app3.step(); // counter: 7 → 8
    const step2c = await app3.step(); // should go to 'high'
    expect(step2c?.action.name).toBe('high');
  });

  // Tests that run() produces identical state to manually calling step() in sequence.
  // Verifies run() is truly just a loop over step() with no hidden behavior or side effects.
  test('run() state matches manual step() sequence', async () => {
    const graph = new GraphBuilder()
      .withActions({ counter, result })
      .withTransitions(
        ['counter', 'counter', (state) => state.count < 3],
        ['counter', 'result']
      )
      .build();

    // App 1: Use run()
    const app1 = new ApplicationBuilder()
      .withGraph(graph)
      .withState(createState(z.object({ count: z.number() }), { count: 0 }))
      .withEntrypoint('counter')
      .withIdentifiers('app1')
      .build();

    const runResult = await app1.run();

    // App 2: Manual step() calls
    const app2 = new ApplicationBuilder()
      .withGraph(graph)
      .withState(createState(z.object({ count: z.number() }), { count: 0 }))
      .withEntrypoint('counter')
      .withIdentifiers('app2')
      .build();

    let lastStep = await app2.step(); // counter: 0 → 1
    lastStep = await app2.step();     // counter: 1 → 2
    lastStep = await app2.step();     // counter: 2 → 3
    lastStep = await app2.step();     // result
    const finalStep = await app2.step(); // terminal

    // States should be identical (except appId)
    expect(runResult.state.data.count).toBe(lastStep!.state.data.count);
    expect(runResult.state.data.executionMetadata.priorStep).toBe(lastStep!.state.data.executionMetadata.priorStep);
    expect(runResult.result).toEqual(lastStep!.result);
    expect(finalStep).toBeNull(); // Both should hit terminal
  });
});

// ============================================================================
// Resumption Tests
// ============================================================================

describe('Resumption Tests', () => {
  // Tests that new application instance can resume from existing state mid-execution.
  // Verifies state handoff between application instances with correct metadata tracking.
  test('CRITICAL: application can resume from existing state', async () => {
    const graph = new GraphBuilder()
      .withActions({ counter, result })
      .withTransitions(
        ['counter', 'counter', (state) => state.count < 10],
        ['counter', 'result']
      )
      .build();

    // ============================================
    // PHASE 1: Initial execution (run 3 steps)
    // ============================================
    const app1 = new ApplicationBuilder()
      .withGraph(graph)
      .withState(createState(z.object({ count: z.number() }), { count: 0 }))
      .withEntrypoint('counter')
      .withIdentifiers('workflow-123', 'user-456')
      .build();

    await app1.step(); // 0 → 1
    await app1.step(); // 1 → 2
    await app1.step(); // 2 → 3

    // Capture state after 3 steps
    const intermediateState = app1.state;
    
    // CRITICAL: Verify metadata is present
    expect(intermediateState.data.count).toBe(3);
    expect(intermediateState.data.executionMetadata.sequenceId).toBe(3);
    expect(intermediateState.data.executionMetadata.priorStep).toBe('counter');
    expect(intermediateState.data.appMetadata.appId).toBe('workflow-123');

    // ============================================
    // PHASE 2: Create NEW application with existing state
    // ============================================
    const app2 = new ApplicationBuilder()
      .withGraph(graph)
      .withState(intermediateState as any)
      .withEntrypoint('counter') // Should be ignored - priorStep determines next
      .withIdentifiers('workflow-123', 'user-456')
      .build();

    // CRITICAL: Metadata should be preserved
    expect(app2.state.data.count).toBe(3);
    expect(app2.state.data.executionMetadata.sequenceId).toBe(3);
    expect(app2.state.data.executionMetadata.priorStep).toBe('counter');
    expect(app2.state.data.appMetadata.appId).toBe('workflow-123');

    // ============================================
    // PHASE 3: Resume execution
    // ============================================
    await app2.step(); // 3 → 4 (sequence ID should be 4)
    expect(app2.state.data.count).toBe(4);
    expect(app2.state.data.executionMetadata.sequenceId).toBe(4);

    await app2.step(); // 4 → 5
    await app2.step(); // 5 → 6
    
    // ============================================
    // PHASE 4: Run to completion
    // ============================================
    const final = await app2.run();
    
    expect(final.state.data.count).toBe(10);
    expect(final.state.data.executionMetadata.sequenceId).toBeGreaterThan(3);
    expect(final.state.data.executionMetadata.priorStep).toBe('result');
    expect(final.result).toHaveProperty('value', 10);
  });

  // Tests that resuming from a halted execution continues correctly.
  // Verifies human-in-loop pattern: halt for approval, create new app, resume.
  test('resume from halt continues correctly', async () => {
    const graph = new GraphBuilder()
      .withActions({ counter, result })
      .withTransitions(
        ['counter', 'counter', (state) => state.count < 10],
        ['counter', 'result']
      )
      .build();

    // ============================================
    // PHASE 1: Run until haltAfter
    // ============================================
    const app1 = new ApplicationBuilder()
      .withGraph(graph)
      .withState(createState(z.object({ count: z.number() }), { count: 0 }))
      .withEntrypoint('counter')
      .withIdentifiers('workflow-123')
      .build();

    // Run until we've executed counter once
    const halted = await app1.run({ 
      haltAfter: ['counter'],
    });

    expect(halted.state.data.count).toBe(1);
    expect(halted.action?.name).toBe('counter');

    // ============================================
    // PHASE 2: Create new app with halted state
    // ============================================
    const app2 = new ApplicationBuilder()
      .withGraph(graph)
      .withState(app1.state as any)
      .withEntrypoint('counter')
      .withIdentifiers('workflow-123')
      .build();

    // ============================================
    // PHASE 3: Continue execution
    // ============================================
    // Should continue from count=1, not re-execute the halted action
    await app2.step(); // 1 → 2
    expect(app2.state.data.count).toBe(2);

    // Run to completion
    const final = await app2.run();
    expect(final.state.data.count).toBe(10);
  });

  // Tests that multiple app restarts maintain state consistency.
  // Verifies long-running workflows can be handed off between app instances many times.
  test('multiple app restarts maintain state consistency', async () => {
    const graph = new GraphBuilder()
      .withActions({ counter })
      .withTransitions(['counter', 'counter'])
      .build();

    // Initialize with metadata
    const initialApp = new ApplicationBuilder()
      .withGraph(graph)
      .withState(createState(z.object({ count: z.number() }), { count: 0 }))
      .withEntrypoint('counter')
      .withIdentifiers('app-123', 'partition-1')
      .build();
    
    let currentState = initialApp.state;

    // ============================================
    // Simulate 5 app restart cycles
    // ============================================
    for (let cycle = 0; cycle < 5; cycle++) {
      // Create new app instance with existing state
      const app = new ApplicationBuilder()
        .withGraph(graph)
        .withState(currentState as any)
        .withEntrypoint('counter')
        .withIdentifiers('app-123', 'partition-1')
        .build();

      // Run 2 steps
      await app.step();
      await app.step();

      // Save state for next cycle
      currentState = app.state;

      // Verify sequence ID is correct
      const expectedSequenceId = (cycle + 1) * 2;
      expect(currentState.data.executionMetadata.sequenceId).toBe(expectedSequenceId);
      expect(currentState.data.count).toBe(expectedSequenceId);
    }
    
    // After 5 cycles × 2 steps = 10 steps total
    expect(currentState.data.count).toBe(10);
    expect(currentState.data.executionMetadata.sequenceId).toBe(10);
    expect(currentState.data.appMetadata.appId).toBe('app-123');
  });
});
