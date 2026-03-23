/*
 * Licensed to the Apache Software Foundation (ASF) under one
 * or more contributor license agreements.  See the NOTICE file
 * distributed with this work for additional information
 * regarding copyright ownership.  The ASF licenses this file
 * to you under the Apache License, Version 2.0 (the
 * "License"); you may not use this file except in compliance
 * with the License.  You may obtain a copy of the License at
 *
 *   http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing,
 * software distributed under the License is distributed on an
 * "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
 * KIND, either express or implied.  See the License for the
 * specific language governing permissions and limitations
 * under the License.
 */

import { BuilderNode, BuilderEdge, BuilderBranch, NodeType, NODE_TYPE_META } from './codeGenerator';

let _nodeIdCounter = 0;

export function resetNodeIdCounter() {
  _nodeIdCounter = 0;
}

export function createDefaultNode(nodeType: NodeType): BuilderNode {
  const id = `node_${++_nodeIdCounter}`;
  const prefixes: Record<NodeType, string> = {
    action: 'action',
    input: 'input',
    result: 'result',
    llm_call: 'llm_call',
    api_call: 'api_call',
    code: 'code_block',
    streaming: 'stream',
    loop: 'loop',
    router: 'router'
  };
  const name = `${prefixes[nodeType]}_${_nodeIdCounter}`;

  const node: BuilderNode = {
    id,
    name,
    nodeType,
    reads: [],
    writes: [],
    inputs: [],
    position: { x: 0, y: 0 }
  };

  switch (nodeType) {
    case 'input':
      node.inputs = ['user_input'];
      node.writes = ['user_input'];
      break;
    case 'result':
      node.reads = ['output'];
      break;
    case 'llm_call':
      node.reads = ['prompt'];
      node.writes = ['response'];
      node.llmProvider = 'openai';
      node.llmModel = 'gpt-4';
      break;
    case 'api_call':
      node.writes = ['api_response'];
      node.apiMethod = 'GET';
      node.apiUrl = 'https://api.example.com';
      break;
    case 'streaming':
      node.reads = ['prompt'];
      node.writes = ['output'];
      break;
    case 'loop':
      node.reads = ['items'];
      node.writes = ['current_item', 'loop_index'];
      node.loopVariable = 'items';
      node.itemVariable = 'current_item';
      node.branches = [];
      break;
    case 'router':
      node.reads = ['status'];
      node.branches = [
        { name: 'Branch 1', condition: 'default', firstAction: undefined },
        { name: 'Branch 2', condition: 'default', firstAction: undefined }
      ];
      break;
  }

  return node;
}

export function findNodeById(root: BuilderNode | undefined, id: string): BuilderNode | undefined {
  if (!root) return undefined;
  if (root.id === id) return root;

  // Search in nextAction chain
  const inNext = findNodeById(root.nextAction, id);
  if (inNext) return inNext;

  // Search in loop children
  if (root.firstLoopAction) {
    const inLoop = findNodeById(root.firstLoopAction, id);
    if (inLoop) return inLoop;
  }

  // Search in router branches
  if (root.branches) {
    for (const branch of root.branches) {
      const inBranch = findNodeById(branch.firstAction, id);
      if (inBranch) return inBranch;
    }
  }

  return undefined;
}

export function mapNode(
  root: BuilderNode | undefined,
  id: string,
  fn: (node: BuilderNode) => BuilderNode
): BuilderNode | undefined {
  if (!root) return undefined;

  let updated = root.id === id ? fn(root) : { ...root };

  if (root.nextAction) {
    updated = { ...updated, nextAction: mapNode(root.nextAction, id, fn) };
  }
  if (root.firstLoopAction) {
    updated = { ...updated, firstLoopAction: mapNode(root.firstLoopAction, id, fn) };
  }
  if (root.branches) {
    updated = {
      ...updated,
      branches: root.branches.map((b) => ({
        ...b,
        firstAction: mapNode(b.firstAction, id, fn)
      }))
    };
  }

  return updated;
}

export function insertAfter(
  root: BuilderNode | undefined,
  parentId: string,
  newNode: BuilderNode
): BuilderNode | undefined {
  if (!root) return undefined;

  if (root.id === parentId) {
    return {
      ...root,
      nextAction: { ...newNode, nextAction: root.nextAction }
    };
  }

  return {
    ...root,
    nextAction: insertAfter(root.nextAction, parentId, newNode),
    firstLoopAction: root.firstLoopAction
      ? insertAfter(root.firstLoopAction, parentId, newNode)
      : undefined,
    branches: root.branches?.map((b) => ({
      ...b,
      firstAction: insertAfter(b.firstAction, parentId, newNode)
    }))
  };
}

export function prependToChain(
  newNode: BuilderNode,
  existingHead: BuilderNode | undefined
): BuilderNode {
  return { ...newNode, nextAction: existingHead };
}

export function appendToEnd(
  root: BuilderNode | undefined,
  newNode: BuilderNode
): BuilderNode {
  if (!root) return newNode;
  if (!root.nextAction) {
    return { ...root, nextAction: newNode };
  }
  return { ...root, nextAction: appendToEnd(root.nextAction, newNode) };
}

export function removeFromTree(
  root: BuilderNode | undefined,
  id: string
): BuilderNode | undefined {
  if (!root) return undefined;

  // If root itself is the target, splice it out but preserve its nextAction
  // (loop children and branch children belong to the node, so they are removed with it)
  if (root.id === id) {
    return root.nextAction;
  }

  return {
    ...root,
    nextAction: removeFromTree(root.nextAction, id),
    firstLoopAction: root.firstLoopAction
      ? removeFromTree(root.firstLoopAction, id)
      : undefined,
    branches: root.branches?.map((b) => ({
      ...b,
      firstAction: removeFromTree(b.firstAction, id)
    }))
  };
}

function collectChain(node: BuilderNode | undefined): BuilderNode[] {
  if (!node) return [];
  return [node, ...collectChain(node.nextAction)];
}

export function flattenTree(
  root: BuilderNode | undefined
): { nodes: BuilderNode[]; edges: BuilderEdge[] } {
  if (!root) return { nodes: [], edges: [] };

  const nodes: BuilderNode[] = [];
  const edges: BuilderEdge[] = [];
  let edgeCounter = 0;

  function walk(node: BuilderNode | undefined) {
    if (!node) return;
    nodes.push(node);

    // nextAction edge (skip for router nodes since branches handle convergence)
    if (node.nextAction) {
      const hasRouterBranches = node.branches && node.branches.length > 0;
      if (!hasRouterBranches) {
        edges.push({
          id: `edge_${++edgeCounter}`,
          source: node.name,
          target: node.nextAction.name,
          condition: 'default'
        });
      }
      walk(node.nextAction);
    }

    // Loop children
    if (node.firstLoopAction) {
      edges.push({
        id: `edge_${++edgeCounter}`,
        source: node.name,
        target: node.firstLoopAction.name,
        condition: node.loopVariable
          ? `expr("${node.loopVariable}_index < len(${node.loopVariable})")`
          : 'default'
      });
      walk(node.firstLoopAction);

      // Return edge from last child back to loop (for code gen)
      const chain = collectChain(node.firstLoopAction);
      const lastChild = chain[chain.length - 1];
      if (lastChild) {
        edges.push({
          id: `edge_${++edgeCounter}`,
          source: lastChild.name,
          target: node.name,
          condition: 'default'
        });
      }
    }

    // Router branches
    if (node.branches) {
      for (const branch of node.branches) {
        if (branch.firstAction) {
          edges.push({
            id: `edge_${++edgeCounter}`,
            source: node.name,
            target: branch.firstAction.name,
            condition: branch.condition
          });
          walk(branch.firstAction);

          // Edge from last in branch to node.nextAction (if exists)
          const chain = collectChain(branch.firstAction);
          const lastInBranch = chain[chain.length - 1];
          if (lastInBranch && node.nextAction) {
            edges.push({
              id: `edge_${++edgeCounter}`,
              source: lastInBranch.name,
              target: node.nextAction.name,
              condition: 'default'
            });
          }
        }
      }
    }
  }

  walk(root);
  return { nodes, edges };
}
