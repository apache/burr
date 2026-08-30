/**
 * Copyright (c) 2024-2025 Elijah ben Izzy
 * SPDX-License-Identifier: Apache-2.0
 */

import { z } from 'zod';
import { action } from '../action';
import { Graph, GraphBuilder } from '../graph';

describe('GraphBuilder', () => {
  // Test actions
  const action1 = action({
    reads: z.object({ count: z.number() }),
    writes: z.object({ count: z.number(), result: z.string() }),
    update: ({ state }) => state.update({ count: state.count + 1, result: 'done' })
  });

  const action2 = action({
    reads: z.object({ result: z.string() }),
    writes: z.object({ final: z.boolean() }),
    update: ({ state }) => state.update({ final: true })
  });

  const action3 = action({
    reads: z.object({ final: z.boolean() }),
    writes: z.object({ message: z.string() }),
    update: ({ state }) => state.update({ message: 'complete' })
  });

  describe('withActions', () => {
    test('adds single action', () => {
      const builder = new GraphBuilder().withActions({ action1 });
      const graph = builder.build();
      
      expect(graph.hasAction('action1')).toBe(true);
      expect(graph.actionCount).toBe(1);
    });

    test('adds multiple actions in single call', () => {
      const builder = new GraphBuilder().withActions({ action1, action2 });
      const graph = builder.build();
      
      expect(graph.hasAction('action1')).toBe(true);
      expect(graph.hasAction('action2')).toBe(true);
      expect(graph.actionCount).toBe(2);
    });

    test('chains multiple withActions calls', () => {
      const builder = new GraphBuilder()
        .withActions({ action1 })
        .withActions({ action2 })
        .withActions({ action3 });
      
      const graph = builder.build();
      
      expect(graph.hasAction('action1')).toBe(true);
      expect(graph.hasAction('action2')).toBe(true);
      expect(graph.hasAction('action3')).toBe(true);
      expect(graph.actionCount).toBe(3);
    });

    test('allows custom action names', () => {
      const builder = new GraphBuilder().withActions({
        first: action1,
        second: action2
      });
      
      const graph = builder.build();
      
      expect(graph.hasAction('first')).toBe(true);
      expect(graph.hasAction('second')).toBe(true);
      expect(graph.hasAction('action1')).toBe(false);
    });

    test('throws on duplicate action names', () => {
      const builder = new GraphBuilder().withActions({ action1 });
      
      expect(() => {
        builder.withActions({ action1 });
      }).toThrow('Duplicate action names: action1');
    });
  });

  describe('withTransitions', () => {
    test('adds transition without condition', () => {
      const builder = new GraphBuilder()
        .withActions({ action1, action2 })
        .withTransitions(['action1', 'action2']);
      
      const graph = builder.build();
      
      expect(graph.transitionCount).toBe(1);
      const transitions = graph.getTransitionsFrom('action1');
      expect(transitions).toHaveLength(1);
      expect(transitions[0].from).toBe('action1');
      expect(transitions[0].to).toBe('action2');
      expect(transitions[0].condition).toBeUndefined();
    });

    test('adds transition with condition', () => {
      const condition = (state: any) => state.count > 5;
      
      const builder = new GraphBuilder()
        .withActions({ action1, action2 })
        .withTransitions(['action1', 'action2', condition]);
      
      const graph = builder.build();
      
      const transitions = graph.getTransitionsFrom('action1');
      expect(transitions[0].condition).toBe(condition);
    });

    test('allows null as terminal target', () => {
      const builder = new GraphBuilder()
        .withActions({ action1 })
        .withTransitions(['action1', null]);
      
      const graph = builder.build();
      
      const transitions = graph.getTransitionsFrom('action1');
      expect(transitions[0].to).toBeNull();
    });

    test('throws if from action not found', () => {
      const builder = new GraphBuilder()
        .withActions({ action1 });
      
      expect(() => {
        builder.withTransitions(['nonexistent', 'action1'] as any);
      }).toThrow("Transition source 'nonexistent' not found in actions");
    });

    test('throws if to action not found', () => {
      const builder = new GraphBuilder()
        .withActions({ action1 });
      
      expect(() => {
        builder.withTransitions(['action1', 'nonexistent'] as any);
      }).toThrow("Transition target 'nonexistent' not found in actions");
    });
  });

  describe('build', () => {
    test('creates graph with actions and transitions', () => {
      const builder = new GraphBuilder()
        .withActions({ action1, action2 })
        .withTransitions(['action1', 'action2']);
      
      const graph = builder.build();
      
      expect(graph).toBeInstanceOf(Graph);
      expect(graph.actionCount).toBe(2);
      expect(graph.transitionCount).toBe(1);
    });

    test('throws if no actions added', () => {
      const builder = new GraphBuilder();
      
      expect(() => {
        builder.build();
      }).toThrow('Cannot build graph with no actions');
    });
  });
});

describe('Graph', () => {
  const action1 = action({
    reads: z.object({ count: z.number() }),
    writes: z.object({ count: z.number() }),
    update: ({ state }) => state.update({ count: state.count + 1 })
  });

  const action2 = action({
    reads: z.object({ count: z.number() }),
    writes: z.object({ result: z.string() }),
    update: ({ state }) => state.update({ result: 'done' })
  });

  test('hasAction works correctly', () => {
    const graph = new GraphBuilder()
      .withActions({ action1 })
      .build();
    
    expect(graph.hasAction('action1')).toBe(true);
    expect(graph.hasAction('nonexistent')).toBe(false);
  });

  test('getAction works correctly', () => {
    const graph = new GraphBuilder()
      .withActions({ action1 })
      .build();
    
    const retrieved = graph.getAction('action1');
    expect(retrieved).toBeDefined();
    expect(retrieved?.name).toBe('action1'); // GraphBuilder sets the name
    expect(graph.getAction('nonexistent')).toBeUndefined();
  });

  test('getTransitionsFrom works correctly', () => {
    const graph = new GraphBuilder()
      .withActions({ action1, action2 })
      .withTransitions(['action1', 'action2'])
      .build();
    
    const transitions = graph.getTransitionsFrom('action1');
    expect(transitions).toHaveLength(1);
    expect(transitions[0].from).toBe('action1');
    expect(transitions[0].to).toBe('action2');
  });
});
