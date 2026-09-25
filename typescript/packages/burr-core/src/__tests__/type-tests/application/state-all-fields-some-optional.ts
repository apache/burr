/**
 * Copyright (c) 2024-2025 Elijah ben Izzy
 * SPDX-License-Identifier: Apache-2.0
 */
export const TEST_META = {
  type: "pass",
  category: "application",
  description: "State can declare all graph fields with some as optional"
};
// START_TEST
import { z } from 'zod';
import { action, GraphBuilder, ApplicationBuilder, createState } from '../../../index';

const counter = action({
  reads: z.object({ count: z.number() }),
  writes: z.object({ count: z.number() }),
  update: ({ state }) => state.update({ count: state.count + 1 })
});

const setLevel = action({
  reads: z.object({ count: z.number() }),
  writes: z.object({ level: z.string() }),
  update: ({ state }) => state.update({ level: 'newLevel' })
});

const graph = new GraphBuilder()
  .withActions({ counter, setLevel })
  .build();

// Graph type: { count: number, level: string } (both required in graph)
// State declares both but level is optional (will be created by setLevel)
const state = createState(
  z.object({ 
    count: z.number(),
    level: z.string().optional()  // Declared but optional
  }),
  { count: 0 }  // level is undefined initially
);

const app = new ApplicationBuilder()
  .withGraph(graph)
  .withEntrypoint('counter')
  .withState(state)
  .build();

const _unused = app;

