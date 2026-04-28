import { z } from "zod";
import { action, ApplicationBuilder, GraphBuilder, createState, createStateWithDefaults } from "../src";

const counter = action({
    reads: z.object({ counter: z.number() }),
    writes: z.object({ counter: z.number() }),
    update: ({ state }) => state.update({ counter: state.counter + 1 })
});

// Build graph (bottom-up: infers state schema from actions)
const graph = new GraphBuilder()
    .withActions({ counter })
    .build();

// ❌ This should fail - state has WRONG but graph needs counter
export const appWithError = new ApplicationBuilder()
    .withEntrypoint('counter')
    .withState(createState(
        z.object({ WRONG: z.number() }),
        { WRONG: 0 }
    ))
    // @ts-expect-error - Intentional: Graph requires { counter } but state has { WRONG }
    .withGraph(graph)
    .build();

// ✅ This works - state has counter as required
export const appCorrect = new ApplicationBuilder()
    .withGraph(graph)
    .withEntrypoint('counter')
    .withState(createState(
        z.object({ counter: z.number() }),
        { counter: 0 }
    ))
    .build();

console.log('Application built successfully:', {
    entrypoint: appCorrect.entrypoint,
    initialState: appCorrect.initialState.counter
});

// ✨ Power-user mode: Use defaults from schema

export const appWithDefaults = new ApplicationBuilder()
    .withGraph(graph)
    .withEntrypoint('counter')
    .withState(createStateWithDefaults(z.object({ counter: z.number().default(0) })))  // No data param needed!
    .build();

console.log('Application with defaults:', {
    entrypoint: appWithDefaults.entrypoint,
    initialState: appWithDefaults.initialState.counter
});



import { Action} from '../src';

// ============================================================================
// Reproduce the EXACT pattern from email-assistant
// ============================================================================

// 1. Define global state schema
const EmailAssistantState = z.object({
  a: z.string(),
  b: z.number(),
  c: z.boolean(),
});

// 2. Create actions using .pick()
const action1 = action({
  reads: EmailAssistantState.pick({ a: true }),
  writes: EmailAssistantState.pick({ b: true }),
  update: ({ state }) => state.update({ b: 42 })
});

const action2 = action({
  reads: EmailAssistantState.pick({ b: true }),
  writes: EmailAssistantState.pick({ c: true }),
  update: ({ state }) => state.update({ c: true }).update({d: false})
});

// 3. Build graph - this creates the complex UnionOfActionStates type
const graph2 = new GraphBuilder()
  .withActions({ action1, action2 })
  .build();

// 4. Create state with full schema
const state = createState(EmailAssistantState, {
  a: 'test',
  b: 0,
  c: false,
});

// 5. Build application - THIS IS WHERE IT SHOULD WORK BUT DOESN'T
const app = new ApplicationBuilder()
  .withGraph(graph2)
  .withEntrypoint('action1')
  .withState(state)  // <-- Should this compile?
  .build();

console.log('If this compiles, our validation works!');
console.log('App:', app);