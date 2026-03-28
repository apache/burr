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

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { BuilderNode, NodeType, generatePythonCode, generateProjectFiles, ProjectFile } from '../utils/codeGenerator';
import { getUnresolvedReads } from '../utils/stateFlow';
import { ActionModel, ApplicationModel, TransitionModel } from '../api';
import {
  createDefaultNode,
  mapNode,
  insertAfter,
  appendToEnd,
  removeFromTree,
  flattenTree,
  resetNodeIdCounter
} from '../utils/treeUtils';
import { buildFlowGraph } from '../utils/flowLayout';
import { InsertContext, InsertLocation, BurrGraph } from '../utils/builderTypes';
// codeParser is used by BuilderView for bidirectional sync

export const useBuilderState = () => {
  const [rootNode, setRootNode] = useState<BuilderNode | null>(null);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);

  // Undo/Redo history
  const undoStack = useRef<(BuilderNode | null)[]>([]);
  const redoStack = useRef<(BuilderNode | null)[]>([]);
  const clipboardRef = useRef<BuilderNode | null>(null);

  const pushUndo = useCallback((state: BuilderNode | null) => {
    undoStack.current.push(state ? JSON.parse(JSON.stringify(state)) : null);
    if (undoStack.current.length > 50) undoStack.current.shift();
    redoStack.current = [];
  }, []);

  const undo = useCallback(() => {
    if (undoStack.current.length === 0) return;
    redoStack.current.push(rootNode ? JSON.parse(JSON.stringify(rootNode)) : null);
    const prev = undoStack.current.pop()!;
    setRootNode(prev);
  }, [rootNode]);

  const redo = useCallback(() => {
    if (redoStack.current.length === 0) return;
    undoStack.current.push(rootNode ? JSON.parse(JSON.stringify(rootNode)) : null);
    const next = redoStack.current.pop()!;
    setRootNode(next);
  }, [rootNode]);

  const copyNode = useCallback(() => {
    if (!selectedNodeId || !rootNode) return;
    const node = flattenTree(rootNode).nodes.find((n) => n.id === selectedNodeId);
    if (node) clipboardRef.current = JSON.parse(JSON.stringify({ ...node, nextAction: undefined }));
  }, [selectedNodeId, rootNode]);

  const pasteNode = useCallback(() => {
    if (!clipboardRef.current || !rootNode) return;
    const pasted = createDefaultNode(clipboardRef.current.nodeType);
    pasted.name = `${clipboardRef.current.name}_copy`;
    pasted.reads = [...clipboardRef.current.reads];
    pasted.writes = [...clipboardRef.current.writes];
    pasted.inputs = [...clipboardRef.current.inputs];
    pasted.codeBody = clipboardRef.current.codeBody;
    pasted.llmProvider = clipboardRef.current.llmProvider;
    pasted.llmModel = clipboardRef.current.llmModel;
    pasted.apiUrl = clipboardRef.current.apiUrl;
    pasted.apiMethod = clipboardRef.current.apiMethod;
    pushUndo(rootNode);
    setRootNode((prev) => (prev ? appendToEnd(prev, pasted) : pasted));
  }, [rootNode, pushUndo]);

  // Keyboard shortcuts (only when Monaco editor is NOT focused)
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      // Let Monaco handle its own keyboard events
      const active = document.activeElement;
      const isInEditor =
        active?.closest('.monaco-editor') !== null ||
        active?.tagName === 'TEXTAREA' ||
        active?.tagName === 'INPUT';
      if (isInEditor) return;

      // Delete/Backspace without modifier
      if (e.key === 'Delete' || e.key === 'Backspace') {
        if (selectedNodeId) {
          e.preventDefault();
          pushUndo(rootNode);
          setRootNode((prev) => (prev ? removeFromTree(prev, selectedNodeId) ?? null : null));
          setSelectedNodeId(null);
        }
        return;
      }

      const isMod = e.ctrlKey || e.metaKey;
      if (!isMod) return;

      if (e.key === 'z' && !e.shiftKey) {
        e.preventDefault();
        undo();
      } else if ((e.key === 'z' && e.shiftKey) || e.key === 'y') {
        e.preventDefault();
        redo();
      } else if (e.key === 'c') {
        copyNode();
      } else if (e.key === 'v') {
        e.preventDefault();
        pasteNode();
      }
    };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [undo, redo, copyNode, pasteNode, selectedNodeId, rootNode, pushUndo]);

  // Derived flat arrays for code gen and validation
  const { nodes: flatNodes, edges: flatEdges } = useMemo(
    () => flattenTree(rootNode ?? undefined),
    [rootNode]
  );

  const entrypoint = rootNode?.name || '';

  // Derived layout graph for ReactFlow
  const layoutGraph: BurrGraph = useMemo(
    () => (rootNode ? buildFlowGraph(rootNode) : { nodes: [], edges: [] }),
    [rootNode]
  );

  // Tree mutation helper (with undo)
  const updateTree = useCallback(
    (updater: (root: BuilderNode) => BuilderNode | undefined) => {
      setRootNode((prev) => {
        if (!prev) return null;
        pushUndo(prev);
        return updater(prev) ?? null;
      });
    },
    [pushUndo]
  );

  // Add node to end of main chain (toolbar action)
  const addNode = useCallback(
    (_position: { x: number; y: number }, nodeType: NodeType = 'action') => {
      const newNode = createDefaultNode(nodeType);
      setRootNode((prev) => {
        pushUndo(prev);
        return prev ? appendToEnd(prev, newNode) : newNode;
      });
      return newNode.id;
    },
    [pushUndo]
  );

  // Insert node after a specific parent (from + button)
  const insertNodeAfter = useCallback(
    (parentId: string, nodeType: NodeType) => {
      const newNode = createDefaultNode(nodeType);
      setRootNode((prev) => {
        if (!prev) return prev;
        pushUndo(prev);
        return insertAfter(prev, parentId, newNode) ?? prev;
      });
    },
    [pushUndo]
  );

  // Insert into loop body (prepend to loop chain)
  const insertIntoLoop = useCallback(
    (loopId: string, nodeType: NodeType) => {
      const newNode = createDefaultNode(nodeType);
      updateTree((root) =>
        mapNode(root, loopId, (loop) => ({
          ...loop,
          firstLoopAction: { ...newNode, nextAction: loop.firstLoopAction }
        }))
      );
    },
    [updateTree]
  );

  // Insert into router branch
  const insertIntoBranch = useCallback(
    (routerId: string, branchIndex: number, nodeType: NodeType) => {
      const newNode = createDefaultNode(nodeType);
      updateTree((root) =>
        mapNode(root, routerId, (router) => {
          const branches = [...(router.branches || [])];
          if (branches[branchIndex]) {
            branches[branchIndex] = {
              ...branches[branchIndex],
              firstAction: { ...newNode, nextAction: branches[branchIndex].firstAction }
            };
          }
          return { ...router, branches };
        })
      );
    },
    [updateTree]
  );

  // Handle insert from any context (used by InlineAddButton)
  const handleInsert = useCallback(
    (nodeType: NodeType, ctx: InsertContext) => {
      switch (ctx.location) {
        case InsertLocation.AFTER:
          insertNodeAfter(ctx.parentStepId, nodeType);
          break;
        case InsertLocation.INSIDE_LOOP:
          insertIntoLoop(ctx.loopStepId, nodeType);
          break;
        case InsertLocation.INSIDE_BRANCH:
          insertIntoBranch(ctx.routerStepId, ctx.branchIndex, nodeType);
          break;
      }
    },
    [insertNodeAfter, insertIntoLoop, insertIntoBranch]
  );

  const updateNode = useCallback(
    (id: string, updates: Partial<BuilderNode>) => {
      updateTree((root) => mapNode(root, id, (node) => ({ ...node, ...updates })));
    },
    [updateTree]
  );

  const removeNode = useCallback(
    (id: string) => {
      setRootNode((prev) => {
        if (!prev) return null;
        pushUndo(prev);
        return removeFromTree(prev, id) ?? null;
      });
      if (selectedNodeId === id) setSelectedNodeId(null);
    },
    [selectedNodeId, pushUndo]
  );

  const addBranch = useCallback(
    (routerId: string, name: string, condition: string) => {
      updateTree((root) =>
        mapNode(root, routerId, (router) => ({
          ...router,
          branches: [...(router.branches || []), { name, condition, firstAction: undefined }]
        }))
      );
    },
    [updateTree]
  );

  const removeBranch = useCallback(
    (routerId: string, branchIndex: number) => {
      updateTree((root) =>
        mapNode(root, routerId, (router) => ({
          ...router,
          branches: (router.branches || []).filter((_, i) => i !== branchIndex)
        }))
      );
    },
    [updateTree]
  );

  // Validation
  const asActions: ActionModel[] = useMemo(
    () =>
      flatNodes.map((n) => ({
        name: n.name || '',
        reads: n.reads || [],
        writes: n.writes || [],
        code: '',
        inputs: n.inputs || [],
        optional_inputs: []
      })),
    [flatNodes]
  );

  const asTransitions: TransitionModel[] = useMemo(
    () =>
      flatEdges.map((e) => ({
        from_: e.source,
        to: e.target,
        condition: e.condition
      })),
    [flatEdges]
  );

  const validationErrors = useMemo(
    () => getUnresolvedReads(asActions, asTransitions),
    [asActions, asTransitions]
  );

  // Code generation
  const generatedCode = useMemo(
    () => generatePythonCode(flatNodes, flatEdges, entrypoint),
    [flatNodes, flatEdges, entrypoint]
  );

  // Multi-file project generation
  const projectFiles: ProjectFile[] = useMemo(
    () => generateProjectFiles(flatNodes, flatEdges, entrypoint),
    [flatNodes, flatEdges, entrypoint]
  );

  // Import from existing application
  const importFromApplication = useCallback((app: ApplicationModel) => {
    resetNodeIdCounter();
    // Build flat nodes first, then chain them linearly
    const nodeMap = new Map<string, BuilderNode>();
    app.actions.forEach((action) => {
      const node = createDefaultNode('action');
      node.name = action.name;
      node.reads = action.reads;
      node.writes = action.writes;
      node.inputs = action.inputs || [];
      nodeMap.set(action.name, node);
    });

    // Chain via transitions immutably
    if (app.entrypoint && nodeMap.has(app.entrypoint)) {
      const visited = new Set<string>();
      const buildChain = (name: string): BuilderNode | undefined => {
        if (visited.has(name) || !nodeMap.has(name)) return undefined;
        visited.add(name);
        const node = { ...nodeMap.get(name)! };
        const nextTransition = app.transitions.find((t) => t.from_ === name && !visited.has(t.to));
        if (nextTransition) {
          node.nextAction = buildChain(nextTransition.to);
        }
        return node;
      };
      const root = buildChain(app.entrypoint);
      if (root) setRootNode(root);
    }
    setSelectedNodeId(null);
  }, []);

  // Set root from code parser (bidirectional sync)
  const setRootFromCode = useCallback(
    (newRoot: BuilderNode) => {
      pushUndo(rootNode);
      setRootNode(newRoot);
    },
    [rootNode, pushUndo]
  );

  // Find selected node in tree
  const selectedNode = useMemo(() => {
    if (!selectedNodeId || !rootNode) return undefined;
    return flatNodes.find((n) => n.id === selectedNodeId);
  }, [selectedNodeId, flatNodes, rootNode]);

  return {
    rootNode,
    setRootNode,
    nodes: flatNodes,
    edges: flatEdges,
    layoutGraph,
    selectedNodeId,
    setSelectedNodeId,
    selectedNode,
    entrypoint,
    addNode,
    insertNodeAfter,
    insertIntoLoop,
    insertIntoBranch,
    handleInsert,
    updateNode,
    removeNode,
    addBranch,
    removeBranch,
    validationErrors,
    generatedCode,
    importFromApplication,
    asActions,
    asTransitions,
    projectFiles,
    setRootFromCode,
    undo,
    redo,
    copyNode,
    pasteNode
  };
};
