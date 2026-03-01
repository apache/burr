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

import React, { useState, useCallback, useEffect, useMemo, useRef } from 'react';
import {
  ReactFlow,
  Node,
  Edge,
  addEdge,
  Connection,
  useNodesState,
  useEdgesState,
  Controls,
  MiniMap,
  Background,
  BackgroundVariant,
  NodeTypes,
  EdgeTypes,
  ReactFlowInstance,
  MarkerType
} from '@xyflow/react';
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter';
import { vscDarkPlus } from 'react-syntax-highlighter/dist/esm/styles/prism';
import { Button } from '../../../common/button';
import {
  PlusIcon,
  ChevronLeftIcon,
  ChevronRightIcon,
  ClipboardDocumentIcon,
  QuestionMarkCircleIcon,
  TrashIcon
} from '@heroicons/react/24/outline';

import '@xyflow/react/dist/style.css';
import CustomNode from './CustomNode';
import CustomEdge from './CustomEdge';
import ExampleGallery from './ExampleGallery';
import ConfirmLoadExampleDialog from './ConfirmLoadExampleDialog';
import { GraphExporter, BurrGraphJSON } from '../utils/GraphExporter';
import { BurrGraphCodeGenerator } from '../utils/BurrCodeGenerator';
import { ExampleLoader } from '../utils/ExampleLoader';
import { examples } from '../data/examples';
import type { ExampleGraph } from '../data/examples';

const nodeTypes: NodeTypes = {
  custom: CustomNode as NodeTypes['custom']
};

const edgeTypes: EdgeTypes = {
  custom: CustomEdge as EdgeTypes['custom']
};

const defaultEdgeOptions = {
  type: 'custom',
  markerEnd: {
    type: MarkerType.ArrowClosed,
    width: 15,
    height: 15,
    color: '#429dbce6'
  }
};

const STORAGE_KEY = 'burr-graph-builder-state';

const nodeTemplates = [
  { type: 'action', label: 'Action' },
  { type: 'input', label: 'Input' }
];

interface NodeDialogData {
  label: string;
  description: string;
  nodeType: string;
  icon: string;
}

/**
 * Visual graph builder for Burr applications.
 *
 * Accepts an optional initialGraph to pre-populate the canvas - this enables
 * future flows like loading from the tracking API or from Pyodide-based
 * Python AST parsing.
 */
interface GraphBuilderProps {
  initialGraph?: BurrGraphJSON;
}

const GraphBuilder: React.FC<GraphBuilderProps> = ({ initialGraph }) => {
  const nodeIdCounter = useRef(0);
  const [leftOpen, setLeftOpen] = useState(true);
  const [rightOpen, setRightOpen] = useState(true);
  const [nodes, setNodes, onNodesChange] = useNodesState([] as Node[]);
  const [edges, setEdges, onEdgesChange] = useEdgesState([] as Edge[]);
  const [reactFlowInstance, setReactFlowInstance] = useState<ReactFlowInstance | null>(null);
  const [nodeDialog, setNodeDialog] = useState(false);
  const [selectedEdge, setSelectedEdge] = useState<string | null>(null);
  const [selectedNode, setSelectedNode] = useState<string | null>(null);
  const [colorPickerOpen, setColorPickerOpen] = useState(false);
  const [colorPickerAnchor, setColorPickerAnchor] = useState<HTMLElement | null>(null);
  const [confirmDialogOpen, setConfirmDialogOpen] = useState(false);
  const [selectedExample, setSelectedExample] = useState<ExampleGraph | null>(null);
  const [nodeDialogData, setNodeDialogData] = useState<NodeDialogData>({
    label: '',
    description: '',
    nodeType: 'action',
    icon: 'settings'
  });
  const [tabIndex, setTabIndex] = useState(0);
  const [copied, setCopied] = useState<'python' | 'json' | null>(null);
  const [showExamplePicker, setShowExamplePicker] = useState(false);

  const edgeColors = [
    '#429dbce6',
    '#ef4444',
    '#10b981',
    '#f59e0b',
    '#8b5cf6',
    '#ec4899',
    '#6b7280'
  ];

  const handleDeleteNode = useCallback(
    (nodeId: string) => {
      setNodes((nds) => nds.filter((node) => node.id !== nodeId));
      setEdges((eds) => eds.filter((edge) => edge.source !== nodeId && edge.target !== nodeId));
      setSelectedNode(null);
    },
    [setNodes, setEdges]
  );

  const handleLabelChange = useCallback(
    (nodeId: string, newLabel: string) => {
      setNodes((nds) =>
        nds.map((node) =>
          node.id === nodeId ? { ...node, data: { ...node.data, label: newLabel } } : node
        )
      );
    },
    [setNodes]
  );

  const handleToggleProperty = useCallback(
    (nodeId: string, property: 'isAsync' | 'isStreaming') => {
      setNodes((nds) =>
        nds.map((node) =>
          node.id === nodeId
            ? { ...node, data: { ...node.data, [property]: !node.data[property] } }
            : node
        )
      );
    },
    [setNodes]
  );

  const handleEdgeLabelChange = useCallback(
    (edgeId: string, newLabel: string) => {
      setEdges((eds) =>
        eds.map((edge) =>
          edge.id === edgeId
            ? { ...edge, data: { ...edge.data, label: newLabel, condition: newLabel } }
            : edge
        )
      );
    },
    [setEdges]
  );

  // Shared helper: convert BurrGraphJSON into ReactFlow nodes/edges and load them
  const loadGraphIntoCanvas = useCallback(
    (graphJson: BurrGraphJSON) => {
      const newNodes: Node[] = graphJson.nodes.map((n, i) => ({
        id: n.id,
        type: 'custom',
        position: n.position,
        data: {
          label: n.label,
          description: n.description || '',
          nodeType: n.nodeType,
          isAsync: n.isAsync || false,
          isStreaming: n.isStreaming || false,
          icon: 'settings',
          colorIndex: i % 10,
          onDelete: handleDeleteNode,
          onLabelChange: handleLabelChange,
          onToggleProperty: handleToggleProperty
        }
      }));

      const newEdges: Edge[] = graphJson.edges.map((e) => ({
        id: e.id,
        source: e.source,
        target: e.target,
        type: 'custom',
        markerEnd: {
          type: MarkerType.ArrowClosed,
          width: 15,
          height: 15,
          color: '#429dbce6'
        },
        data: {
          condition: e.condition,
          isConditional: e.isConditional,
          label: e.condition,
          onLabelChange: handleEdgeLabelChange
        }
      }));

      // Update nodeIdCounter to be higher than any existing node's numeric suffix
      const maxId = graphJson.nodes.reduce((max, n) => {
        const match = n.id.match(/(\d+)$/);
        return match ? Math.max(max, parseInt(match[1], 10)) : max;
      }, 0);
      nodeIdCounter.current = Math.max(nodeIdCounter.current, maxId);

      setNodes(newNodes);
      setEdges(newEdges);
    },
    [
      handleDeleteNode,
      handleLabelChange,
      handleToggleProperty,
      handleEdgeLabelChange,
      setNodes,
      setEdges
    ]
  );

  // Load initialGraph prop if provided, otherwise restore from localStorage
  useEffect(() => {
    if (initialGraph) {
      loadGraphIntoCanvas(initialGraph);
      return;
    }

    try {
      const saved = localStorage.getItem(STORAGE_KEY);
      if (saved) {
        const parsed = JSON.parse(saved) as BurrGraphJSON;
        if (parsed.nodes && parsed.nodes.length > 0) {
          loadGraphIntoCanvas(parsed);
        }
      }
    } catch {
      // Corrupted data — ignore and start fresh
    }
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const onPaneClick = useCallback(
    (event: React.MouseEvent) => {
      if (event.metaKey || event.ctrlKey) {
        const isRightClick = event.button === 2 || event.type === 'contextmenu';
        const nodeType = isRightClick ? 'input' : 'action';
        const nodeLabel = isRightClick ? `Input ${nodes.length + 1}` : `Node ${nodes.length + 1}`;

        let position;
        if (reactFlowInstance) {
          position = reactFlowInstance.screenToFlowPosition({
            x: event.clientX,
            y: event.clientY
          });
        } else {
          const rect = (event.currentTarget as HTMLElement).getBoundingClientRect();
          position = {
            x: event.clientX - rect.left,
            y: event.clientY - rect.top
          };
        }

        const newNode: Node = {
          id: `node_${++nodeIdCounter.current}`,
          type: 'custom',
          position,
          data: {
            label: nodeLabel,
            description: '',
            nodeType: nodeType,
            isAsync: false,
            isStreaming: false,
            icon: 'settings',
            colorIndex: nodes.length % 10,
            onDelete: handleDeleteNode,
            onLabelChange: handleLabelChange,
            onToggleProperty: handleToggleProperty
          }
        };

        setNodes((nds) => [...nds, newNode]);

        if (isRightClick) {
          event.preventDefault();
        }
      }
    },
    [
      nodes.length,
      setNodes,
      handleDeleteNode,
      handleLabelChange,
      handleToggleProperty,
      reactFlowInstance
    ]
  );

  const onPaneContextMenu = useCallback(
    (event: React.MouseEvent | MouseEvent) => {
      const reactEvent = event as React.MouseEvent;
      if (reactEvent.metaKey || reactEvent.ctrlKey) {
        onPaneClick(reactEvent);
      }
    },
    [onPaneClick]
  );

  const onKeyDown = useCallback(
    (event: KeyboardEvent) => {
      const target = event.target as HTMLElement;
      const isInputFocused =
        target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.isContentEditable;

      if ((event.key === 'Backspace' || event.key === 'Delete') && !isInputFocused) {
        if (selectedNode) {
          setNodes((nds) => nds.filter((node) => node.id !== selectedNode));
          setEdges((eds) =>
            eds.filter((edge) => edge.source !== selectedNode && edge.target !== selectedNode)
          );
          setSelectedNode(null);
        } else if (selectedEdge) {
          setEdges((eds) => {
            const filteredEdges = eds.filter((edge) => edge.id !== selectedEdge);

            const deletedEdge = eds.find((edge) => edge.id === selectedEdge);
            if (deletedEdge) {
              const sourceEdges = filteredEdges.filter(
                (edge) => edge.source === deletedEdge.source
              );
              const shouldBeConditional = sourceEdges.length > 1;

              return filteredEdges.map((edge) => {
                if (edge.source === deletedEdge.source) {
                  const preservedLabel = shouldBeConditional
                    ? deletedEdge.data?.label || edge.data?.label || 'condition'
                    : undefined;
                  return {
                    ...edge,
                    data: {
                      ...edge.data,
                      isConditional: shouldBeConditional,
                      label: preservedLabel,
                      onLabelChange: handleEdgeLabelChange
                    }
                  };
                }
                return edge;
              });
            }

            return filteredEdges;
          });
          setSelectedEdge(null);
        }
      }
    },
    [selectedNode, selectedEdge, setNodes, setEdges, handleEdgeLabelChange]
  );

  useEffect(() => {
    document.addEventListener('keydown', onKeyDown);
    return () => {
      document.removeEventListener('keydown', onKeyDown);
    };
  }, [onKeyDown]);

  const onConnect = useCallback(
    (params: Connection) => {
      const sourceEdges = edges.filter((edge) => edge.source === params.source);
      const willBeConditional = sourceEdges.length > 0;

      const targetNode = nodes.find((node) => node.id === params.target);
      const targetLabel = targetNode?.data?.label || params.target;
      const conditionString = `condition="${targetLabel}"`;

      const newEdge = {
        ...params,
        type: 'custom',
        markerEnd: {
          type: MarkerType.ArrowClosed,
          width: 15,
          height: 15,
          color: '#429dbce6'
        },
        data: {
          condition: willBeConditional ? conditionString : undefined,
          isConditional: willBeConditional,
          label: willBeConditional ? conditionString : undefined,
          onLabelChange: handleEdgeLabelChange
        }
      };

      setEdges((eds) => addEdge(newEdge, eds));
    },
    [setEdges, edges, nodes, handleEdgeLabelChange]
  );

  const onNodeClick = useCallback((_event: React.MouseEvent, node: Node) => {
    setSelectedNode(node.id);
    setSelectedEdge(null);
    setColorPickerOpen(false);
    setColorPickerAnchor(null);
  }, []);

  const onEdgeClick = useCallback((_event: React.MouseEvent, edge: Edge) => {
    setSelectedEdge(edge.id);
    setSelectedNode(null);
    setColorPickerAnchor(_event.currentTarget as HTMLElement);
    setColorPickerOpen(true);
  }, []);

  const handleEdgeColorChange = useCallback(
    (color: string) => {
      if (selectedEdge) {
        setEdges((eds) =>
          eds.map((edge) =>
            edge.id === selectedEdge ? { ...edge, style: { ...edge.style, stroke: color } } : edge
          )
        );
      }
      setColorPickerOpen(false);
      setColorPickerAnchor(null);
    },
    [selectedEdge, setEdges]
  );

  const handleToggleConditional = useCallback(() => {
    if (!selectedEdge) return;
    setEdges((eds) => {
      const targetEdge = eds.find((e) => e.id === selectedEdge);
      if (!targetEdge) return eds;
      const source = targetEdge.source;
      const target = targetEdge.target;
      const groupEdges = eds.filter((e) => e.source === source);
      const toggledIsConditional = !targetEdge.data?.isConditional;

      const targetNode = nodes.find((node) => node.id === target);
      const targetLabel = targetNode?.data?.label || target;
      const conditionString = `condition="${targetLabel}"`;

      return eds.map((edge) => {
        if (edge.id === selectedEdge) {
          return {
            ...edge,
            data: {
              ...edge.data,
              isConditional: toggledIsConditional,
              condition: toggledIsConditional ? conditionString : undefined,
              label: toggledIsConditional ? conditionString : undefined
            }
          };
        }
        if (edge.source === source && edge.id !== selectedEdge) {
          if (!toggledIsConditional) {
            const stillConditional =
              groupEdges.filter((e) => e.id !== selectedEdge && e.data?.isConditional).length > 1;
            return {
              ...edge,
              data: {
                ...edge.data,
                isConditional: stillConditional
              }
            };
          }
        }
        return edge;
      });
    });
    setColorPickerOpen(false);
    setColorPickerAnchor(null);
  }, [selectedEdge, setEdges, nodes]);

  const handleAddNode = useCallback(() => {
    setNodeDialog(true);
  }, []);

  const [confirmClearOpen, setConfirmClearOpen] = useState(false);
  const handleClearCanvas = useCallback(() => {
    setNodes([]);
    setEdges([]);
    setSelectedNode(null);
    setSelectedEdge(null);
    nodeIdCounter.current = 0;
    setConfirmClearOpen(false);
    try {
      localStorage.removeItem(STORAGE_KEY);
    } catch {
      // ignore
    }
  }, [setNodes, setEdges]);

  const handleCreateNode = useCallback(() => {
    const newNode: Node = {
      id: `node_${++nodeIdCounter.current}`,
      type: 'custom',
      position: { x: Math.random() * 500 + 100, y: Math.random() * 500 + 100 },
      data: {
        label: nodeDialogData.label,
        description: nodeDialogData.description,
        nodeType: nodeDialogData.nodeType,
        isAsync: false,
        isStreaming: false,
        icon: nodeDialogData.icon,
        colorIndex: nodes.length % 10,
        onDelete: handleDeleteNode,
        onLabelChange: handleLabelChange,
        onToggleProperty: handleToggleProperty
      }
    };

    setNodes((nds) => [...nds, newNode]);
    setNodeDialog(false);
    setNodeDialogData({
      label: '',
      description: '',
      nodeType: 'action',
      icon: 'settings'
    });
  }, [
    nodeDialogData,
    setNodes,
    nodes.length,
    handleDeleteNode,
    handleLabelChange,
    handleToggleProperty
  ]);

  const graphData = useMemo(() => GraphExporter.exportToJSON(nodes, edges), [nodes, edges]);
  const pythonCode = useMemo(
    () => BurrGraphCodeGenerator.generatePythonCode(graphData),
    [graphData]
  );
  const jsonCode = useMemo(() => JSON.stringify(graphData, null, 2), [graphData]);

  // Auto-save graph to localStorage (debounced to avoid writing on every drag frame)
  const saveTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => {
    if (saveTimerRef.current) {
      clearTimeout(saveTimerRef.current);
    }
    saveTimerRef.current = setTimeout(() => {
      try {
        localStorage.setItem(STORAGE_KEY, JSON.stringify(graphData));
      } catch {
        // Storage full or unavailable — silently skip
      }
    }, 500);
    return () => {
      if (saveTimerRef.current) {
        clearTimeout(saveTimerRef.current);
      }
    };
  }, [graphData]);

  const hasExistingContent = nodes.length > 0 || edges.length > 0;

  const handleLoadExample = useCallback((example: ExampleGraph) => {
    setSelectedExample(example);
    setConfirmDialogOpen(true);
  }, []);

  const handleConfirmLoadExample = useCallback(() => {
    if (!selectedExample) return;

    const errors = ExampleLoader.validateExample(selectedExample);
    if (errors.length > 0) {
      return;
    }

    const { nodes: newNodes, edges: newEdges } = ExampleLoader.convertToReactFlow(selectedExample);

    const nodesWithHandlers = newNodes.map((node) => ({
      ...node,
      data: {
        ...node.data,
        onDelete: handleDeleteNode,
        onLabelChange: handleLabelChange,
        onToggleProperty: handleToggleProperty
      }
    }));

    const edgesWithHandlers = newEdges.map((edge) => ({
      ...edge,
      data: {
        ...edge.data,
        onLabelChange: handleEdgeLabelChange
      }
    }));

    setNodes(nodesWithHandlers);
    setEdges(edgesWithHandlers);
    setConfirmDialogOpen(false);
    setSelectedExample(null);

    setTimeout(() => {
      if (reactFlowInstance) {
        reactFlowInstance.fitView({ padding: 0.1 });
      }
    }, 100);
  }, [
    selectedExample,
    handleDeleteNode,
    handleLabelChange,
    handleToggleProperty,
    handleEdgeLabelChange,
    setNodes,
    setEdges,
    reactFlowInstance
  ]);

  const handleCancelLoadExample = useCallback(() => {
    setConfirmDialogOpen(false);
    setSelectedExample(null);
  }, []);

  return (
    <div className="flex h-full overflow-hidden border-t">
      {/* Left sidebar with help & instructions */}
      <div
        className={`${leftOpen ? 'w-72' : 'w-12'} flex-shrink-0 bg-white border-r border-gray-200 transition-all duration-200 overflow-hidden`}
      >
        <div className="flex flex-col h-full">
          {leftOpen ? (
            <div className="flex-1 overflow-auto p-4">
              {/* Intro */}
              <div className="mb-5">
                <h3 className="text-lg font-semibold mb-1">Graph Builder</h3>
                <p className="text-sm text-gray-500">
                  Visually design Burr application graphs, then export as Python code or JSON.
                </p>
              </div>

              {/* Quick Start */}
              <div className="mb-5">
                <h4 className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-3">
                  Quick Start
                </h4>
                <ol className="text-sm text-gray-600 space-y-2 list-decimal list-inside">
                  <li>Add action nodes to the canvas</li>
                  <li>Connect them by dragging between handles</li>
                  <li>
                    Switch to the <span className="font-medium">Python</span> tab to see generated
                    code
                  </li>
                </ol>
              </div>

              {/* Creating */}
              <div className="mb-5">
                <h4 className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-3">
                  Creating
                </h4>
                <div className="space-y-3">
                  <div className="flex items-start gap-2">
                    <div className="flex-shrink-0 mt-0.5">
                      <kbd className="inline-flex items-center px-1.5 py-0.5 rounded bg-gray-100 border border-gray-300 text-xs font-mono text-gray-700">
                        {navigator.platform?.includes('Mac') ? '\u2318' : 'Ctrl'}+Click
                      </kbd>
                    </div>
                    <span className="text-sm text-gray-600">
                      Add an action node at that position
                    </span>
                  </div>
                  <div className="flex items-start gap-2">
                    <div className="flex-shrink-0 mt-0.5">
                      <kbd className="inline-flex items-center px-1.5 py-0.5 rounded bg-gray-100 border border-gray-300 text-xs font-mono text-gray-700">
                        {navigator.platform?.includes('Mac') ? '\u2318' : 'Ctrl'}+Right-click
                      </kbd>
                    </div>
                    <span className="text-sm text-gray-600">Add an input node</span>
                  </div>
                  <div className="flex items-start gap-2">
                    <div className="flex-shrink-0 mt-0.5">
                      <kbd className="inline-flex items-center px-1.5 py-0.5 rounded bg-gray-100 border border-gray-300 text-xs font-mono text-gray-700">
                        Drag
                      </kbd>
                    </div>
                    <span className="text-sm text-gray-600">
                      From bottom handle to top handle to create an edge (transition)
                    </span>
                  </div>
                  <div className="flex items-start gap-2">
                    <div className="flex-shrink-0 mt-0.5">
                      <kbd className="inline-flex items-center px-1.5 py-0.5 rounded bg-gray-100 border border-gray-300 text-xs font-mono text-gray-700">
                        +
                      </kbd>
                    </div>
                    <span className="text-sm text-gray-600">
                      Use the button at the bottom-right to add a node via dialog
                    </span>
                  </div>
                </div>
              </div>

              {/* Editing */}
              <div className="mb-5">
                <h4 className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-3">
                  Editing
                </h4>
                <div className="space-y-3">
                  <div className="flex items-start gap-2">
                    <div className="flex-shrink-0 mt-0.5">
                      <span className="text-sm text-gray-500">Click label</span>
                    </div>
                    <span className="text-sm text-gray-600">Edit a node&apos;s name inline</span>
                  </div>
                  <div className="flex items-start gap-2">
                    <div className="flex-shrink-0 mt-0.5">
                      <span className="text-sm text-gray-500">Click edge label</span>
                    </div>
                    <span className="text-sm text-gray-600">
                      Edit a conditional edge&apos;s condition text
                    </span>
                  </div>
                  <div className="flex items-start gap-2">
                    <div className="flex-shrink-0 mt-0.5">
                      <span className="text-sm text-gray-500">Select node</span>
                    </div>
                    <span className="text-sm text-gray-600">
                      Toggle action/streaming type via the badge in the top-right corner
                    </span>
                  </div>
                  <div className="flex items-start gap-2">
                    <div className="flex-shrink-0 mt-0.5">
                      <span className="text-sm text-gray-500">Click edge</span>
                    </div>
                    <span className="text-sm text-gray-600">
                      Pick a color or toggle conditional/default
                    </span>
                  </div>
                </div>
              </div>

              {/* Deleting */}
              <div className="mb-5">
                <h4 className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-3">
                  Deleting
                </h4>
                <div className="flex items-start gap-2">
                  <div className="flex-shrink-0 mt-0.5">
                    <kbd className="inline-flex items-center px-1.5 py-0.5 rounded bg-gray-100 border border-gray-300 text-xs font-mono text-gray-700">
                      {navigator.platform?.includes('Mac') ? '\u232b' : 'Backspace'}
                    </kbd>
                  </div>
                  <span className="text-sm text-gray-600">Delete the selected node or edge</span>
                </div>
              </div>

              {/* Concepts */}
              <div className="mb-5">
                <h4 className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-3">
                  Node Types
                </h4>
                <div className="space-y-2">
                  <div className="flex items-start gap-2">
                    <span className="inline-block w-3 h-3 rounded bg-blue-200 border border-blue-400 flex-shrink-0 mt-1" />
                    <div>
                      <span className="text-sm font-medium text-gray-700">Action</span>
                      <p className="text-xs text-gray-500">
                        A step decorated with{' '}
                        <code className="bg-gray-100 px-1 rounded">@action</code>
                      </p>
                    </div>
                  </div>
                  <div className="flex items-start gap-2">
                    <span className="inline-block w-3 h-3 rounded border-2 border-dashed border-gray-400 flex-shrink-0 mt-1 w-3 h-3" />
                    <div>
                      <span className="text-sm font-medium text-gray-700">Input</span>
                      <p className="text-xs text-gray-500">
                        External input passed into an action at runtime
                      </p>
                    </div>
                  </div>
                </div>
              </div>

              {/* Node Flags */}
              <div className="mb-5">
                <h4 className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-3">
                  Action Flags
                </h4>
                <p className="text-xs text-gray-500 mb-2">
                  Select a node to toggle these independently:
                </p>
                <div className="space-y-2">
                  <div className="flex items-start gap-2">
                    <span className="inline-flex px-1.5 py-0.5 rounded bg-blue-500 text-white text-[10px] font-semibold flex-shrink-0 mt-0.5">
                      async
                    </span>
                    <p className="text-xs text-gray-500">
                      Makes the function <code className="bg-gray-100 px-1 rounded">async def</code>
                    </p>
                  </div>
                  <div className="flex items-start gap-2">
                    <span className="inline-flex px-1.5 py-0.5 rounded bg-blue-500 text-white text-[10px] font-semibold flex-shrink-0 mt-0.5">
                      stream
                    </span>
                    <p className="text-xs text-gray-500">
                      Uses <code className="bg-gray-100 px-1 rounded">@streaming_action</code> and
                      yields results
                    </p>
                  </div>
                </div>
              </div>

              {/* Edge Types */}
              <div className="mb-5">
                <h4 className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-3">
                  Edge Types
                </h4>
                <div className="space-y-2">
                  <div className="flex items-start gap-2">
                    <span className="inline-block w-6 border-t-2 border-blue-400 flex-shrink-0 mt-2" />
                    <div>
                      <span className="text-sm font-medium text-gray-700">Default</span>
                      <p className="text-xs text-gray-500">
                        Unconditional transition (uses{' '}
                        <code className="bg-gray-100 px-1 rounded">default</code>)
                      </p>
                    </div>
                  </div>
                  <div className="flex items-start gap-2">
                    <span className="inline-block w-6 border-t-2 border-dashed border-blue-400 flex-shrink-0 mt-2" />
                    <div>
                      <span className="text-sm font-medium text-gray-700">Conditional</span>
                      <p className="text-xs text-gray-500">
                        Guarded transition (uses{' '}
                        <code className="bg-gray-100 px-1 rounded">when()</code>). Created
                        automatically when a node has multiple outgoing edges.
                      </p>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          ) : (
            <div className="flex-1 flex items-start justify-center pt-4">
              <QuestionMarkCircleIcon className="w-5 h-5 text-gray-400" />
            </div>
          )}
          <div className={`flex items-center ${leftOpen ? 'justify-start' : 'justify-center'} p-2`}>
            <button
              onClick={() => setLeftOpen(!leftOpen)}
              className="p-1 rounded hover:bg-gray-100"
              title={leftOpen ? 'Collapse help panel' : 'Expand help panel'}
            >
              {leftOpen ? (
                <ChevronLeftIcon className="w-5 h-5 text-gray-400" />
              ) : (
                <ChevronRightIcon className="w-5 h-5 text-gray-400" />
              )}
            </button>
          </div>
        </div>
      </div>

      {/* Main content area */}
      <div className="flex flex-col flex-1 min-w-0">
        {/* Tab navigation */}
        <div className="border-b border-gray-200 flex-shrink-0">
          <nav className="flex space-x-8 px-4">
            {[
              { label: 'Canvas', title: 'Visual graph editor' },
              { label: 'Python', title: 'Generated Burr Python code' },
              { label: 'JSON', title: 'Graph data as JSON (importable)' }
            ].map((tab, idx) => (
              <button
                key={tab.label}
                onClick={() => setTabIndex(idx)}
                title={tab.title}
                className={`py-2 px-1 border-b-2 font-medium text-sm ${
                  tabIndex === idx
                    ? 'border-blue-500 text-blue-600'
                    : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
                }`}
              >
                {tab.label}
              </button>
            ))}
          </nav>
        </div>

        {/* Tab content */}
        <div className="flex-1 min-h-0 relative">
          {tabIndex === 0 && (
            <div className="h-full w-full relative">
              <ReactFlow
                nodes={nodes}
                edges={edges}
                onNodesChange={onNodesChange}
                onEdgesChange={onEdgesChange}
                onConnect={onConnect}
                onNodeClick={onNodeClick}
                onEdgeClick={onEdgeClick}
                onPaneClick={onPaneClick}
                onPaneContextMenu={onPaneContextMenu}
                onInit={setReactFlowInstance}
                nodeTypes={nodeTypes}
                edgeTypes={edgeTypes}
                defaultEdgeOptions={defaultEdgeOptions}
                defaultViewport={{ x: 0, y: 0, zoom: 1.0 }}
                attributionPosition="bottom-left"
                deleteKeyCode={null}
                style={{ width: '100%', height: '100%' }}
              >
                <Controls />
                <MiniMap />
                <Background variant={BackgroundVariant.Dots} gap={20} size={1} />
              </ReactFlow>

              {/* Empty state overlay */}
              {nodes.length === 0 && (
                <div className="absolute inset-0 flex items-center justify-center pointer-events-none z-10">
                  <div className="bg-white/90 backdrop-blur-sm rounded-xl shadow-lg border border-gray-200 p-8 max-w-md text-center pointer-events-auto">
                    <h3 className="text-xl font-semibold text-gray-800 mb-2">
                      Design your Burr graph
                    </h3>
                    <p className="text-sm text-gray-500 mb-6">
                      Build application graphs visually and export as Python code.
                    </p>

                    <div className="text-left space-y-3 mb-6">
                      <div className="flex items-center gap-3 bg-gray-50 rounded-lg px-4 py-2.5">
                        <kbd className="inline-flex items-center px-2 py-1 rounded bg-white border border-gray-300 text-xs font-mono text-gray-700 shadow-sm flex-shrink-0">
                          {navigator.platform?.includes('Mac') ? '\u2318' : 'Ctrl'}+Click
                        </kbd>
                        <span className="text-sm text-gray-600">Add an action node</span>
                      </div>
                      <div className="flex items-center gap-3 bg-gray-50 rounded-lg px-4 py-2.5">
                        <kbd className="inline-flex items-center px-2 py-1 rounded bg-white border border-gray-300 text-xs font-mono text-gray-700 shadow-sm flex-shrink-0">
                          Drag handle
                        </kbd>
                        <span className="text-sm text-gray-600">Connect nodes with edges</span>
                      </div>
                    </div>

                    <div className="flex gap-3 justify-center">
                      <button
                        className="inline-flex items-center px-4 py-2 bg-blue-500 hover:bg-blue-600 text-white text-sm font-medium rounded-lg transition-colors"
                        onClick={handleAddNode}
                      >
                        <PlusIcon className="w-4 h-4 mr-1.5" />
                        Add First Node
                      </button>
                      <button
                        className="inline-flex items-center px-4 py-2 border border-gray-300 text-gray-700 text-sm font-medium rounded-lg hover:bg-gray-50 transition-colors"
                        onClick={() => setShowExamplePicker(true)}
                      >
                        Load Example
                      </button>
                    </div>
                  </div>
                </div>
              )}

              <div className="absolute bottom-4 right-4 flex gap-2">
                {hasExistingContent && (
                  <button
                    className="bg-white hover:bg-red-50 text-red-500 border border-red-200 rounded-full w-14 h-14 flex items-center justify-center shadow-lg transition-colors"
                    onClick={() => setConfirmClearOpen(true)}
                    title="Clear canvas"
                    aria-label="Clear canvas"
                  >
                    <TrashIcon className="w-6 h-6" />
                  </button>
                )}
                <button
                  className="bg-blue-500 hover:bg-blue-600 text-white rounded-full w-14 h-14 flex items-center justify-center shadow-lg transition-colors"
                  onClick={handleAddNode}
                  title="Add a new node via dialog"
                  aria-label="Add a new node"
                >
                  <PlusIcon className="w-6 h-6" />
                </button>
              </div>
            </div>
          )}
          {tabIndex === 1 && (
            <div className="h-full flex flex-col bg-gray-900 relative">
              <div className="absolute top-2 right-5 z-10 bg-white bg-opacity-85 rounded">
                <button
                  className={`p-2 rounded ${
                    copied === 'python' ? 'text-green-600' : 'text-blue-600'
                  } hover:bg-gray-100`}
                  onClick={() => {
                    navigator.clipboard
                      .writeText(pythonCode)
                      .then(() => {
                        setCopied('python');
                        setTimeout(() => setCopied(null), 1200);
                      })
                      .catch(() => {
                        /* clipboard not available */
                      });
                  }}
                  title={copied === 'python' ? 'Copied!' : 'Copy Python code to clipboard'}
                  aria-label="Copy Python code"
                >
                  <ClipboardDocumentIcon className="w-5 h-5" />
                </button>
              </div>
              <div className="flex-1 overflow-auto">
                <SyntaxHighlighter
                  language="python"
                  style={vscDarkPlus}
                  customStyle={{
                    margin: 0,
                    padding: 16,
                    fontSize: 14,
                    borderRadius: 0,
                    minHeight: '100%'
                  }}
                >
                  {pythonCode}
                </SyntaxHighlighter>
              </div>
            </div>
          )}
          {tabIndex === 2 && (
            <div className="h-full flex flex-col bg-gray-900 relative">
              <div className="absolute top-2 right-5 z-10 bg-white bg-opacity-85 rounded">
                <button
                  className={`p-2 rounded ${
                    copied === 'json' ? 'text-green-600' : 'text-blue-600'
                  } hover:bg-gray-100`}
                  onClick={() => {
                    navigator.clipboard
                      .writeText(jsonCode)
                      .then(() => {
                        setCopied('json');
                        setTimeout(() => setCopied(null), 1200);
                      })
                      .catch(() => {
                        /* clipboard not available */
                      });
                  }}
                  title={copied === 'json' ? 'Copied!' : 'Copy JSON to clipboard'}
                  aria-label="Copy JSON code"
                >
                  <ClipboardDocumentIcon className="w-5 h-5" />
                </button>
              </div>
              <div className="flex-1 overflow-auto">
                <SyntaxHighlighter
                  language="json"
                  style={vscDarkPlus}
                  customStyle={{
                    margin: 0,
                    padding: 16,
                    fontSize: 14,
                    borderRadius: 0,
                    minHeight: '100%'
                  }}
                >
                  {jsonCode}
                </SyntaxHighlighter>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Right panel: ExampleGallery */}
      <div
        className={`${rightOpen ? 'w-72' : 'w-12'} flex-shrink-0 bg-white shadow-lg z-10 transition-all duration-200`}
      >
        <div className="flex flex-col h-full">
          {rightOpen ? (
            <div className="flex-1 overflow-y-auto p-4">
              <ExampleGallery examples={examples} onLoadExample={handleLoadExample} />
            </div>
          ) : (
            <div className="flex-1" />
          )}
          <div
            className={`flex items-center ${rightOpen ? 'justify-start' : 'justify-center'} p-2 border-t border-gray-200 bg-white flex-shrink-0`}
          >
            <button
              onClick={() => setRightOpen(!rightOpen)}
              className="p-1 rounded hover:bg-gray-100"
              title={rightOpen ? 'Collapse examples panel' : 'Expand examples panel'}
            >
              {rightOpen ? (
                <ChevronRightIcon className="w-5 h-5 text-gray-400" />
              ) : (
                <ChevronLeftIcon className="w-5 h-5 text-gray-400" />
              )}
            </button>
          </div>
        </div>
      </div>

      {/* Add Node Dialog */}
      {nodeDialog && (
        <div
          className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50"
          onClick={() => setNodeDialog(false)}
        >
          <div
            className="bg-white rounded-lg p-6 w-full max-w-md"
            onClick={(e) => e.stopPropagation()}
          >
            <h2 className="text-lg font-semibold mb-4">Add New Node</h2>
            <div className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Node Label</label>
                <input
                  type="text"
                  value={nodeDialogData.label}
                  onChange={(e) => setNodeDialogData({ ...nodeDialogData, label: e.target.value })}
                  className="w-full border border-gray-300 rounded-md px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Description</label>
                <textarea
                  value={nodeDialogData.description}
                  onChange={(e) =>
                    setNodeDialogData({ ...nodeDialogData, description: e.target.value })
                  }
                  rows={3}
                  className="w-full border border-gray-300 rounded-md px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Node Type</label>
                <select
                  value={nodeDialogData.nodeType}
                  onChange={(e) =>
                    setNodeDialogData({ ...nodeDialogData, nodeType: e.target.value })
                  }
                  className="w-full border border-gray-300 rounded-md px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-500"
                >
                  {nodeTemplates.map((template) => (
                    <option key={template.type} value={template.type}>
                      {template.label}
                    </option>
                  ))}
                </select>
              </div>
            </div>
            <div className="flex justify-end space-x-2 mt-6">
              <Button onClick={() => setNodeDialog(false)} outline>
                Cancel
              </Button>
              <Button onClick={handleCreateNode}>Create Node</Button>
            </div>
          </div>
        </div>
      )}

      {/* Color Picker Popover for Edges */}
      {colorPickerOpen && colorPickerAnchor && (
        <div
          className="fixed z-50 bg-white rounded-lg shadow-lg border border-gray-200 p-4"
          style={{
            top: colorPickerAnchor.getBoundingClientRect().bottom + 8,
            left: colorPickerAnchor.getBoundingClientRect().left
          }}
        >
          <h3 className="text-sm font-medium mb-3">Select Edge Color</h3>
          <div className="grid grid-cols-4 gap-2">
            {edgeColors.map((color) => (
              <button
                key={color}
                className="w-8 h-8 rounded border-2 border-transparent hover:border-black transition-colors"
                style={{ backgroundColor: color }}
                onClick={() => handleEdgeColorChange(color)}
              />
            ))}
          </div>
          {(() => {
            if (!selectedEdge) return null;
            const selected = edges.find((e) => e.id === selectedEdge);
            if (!selected) return null;
            const groupEdges = edges.filter((e) => e.source === selected.source);
            if (groupEdges.length > 1) {
              return (
                <div className="mt-4">
                  {selected.data?.isConditional ? (
                    <Button className="w-full" color="blue" onClick={handleToggleConditional}>
                      Make Default
                    </Button>
                  ) : (
                    <Button className="w-full" outline onClick={handleToggleConditional}>
                      Make Conditional
                    </Button>
                  )}
                </div>
              );
            }
            return null;
          })()}
        </div>
      )}

      {/* Example Picker Modal (from empty state) */}
      {showExamplePicker && (
        <div
          className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50"
          onClick={() => setShowExamplePicker(false)}
        >
          <div
            className="bg-white rounded-lg p-6 w-full max-w-lg max-h-[80vh] overflow-y-auto"
            onClick={(e) => e.stopPropagation()}
          >
            <h2 className="text-lg font-semibold mb-1">Load an Example</h2>
            <p className="text-sm text-gray-500 mb-4">
              Pick a pre-built graph to explore the builder.
            </p>
            <div className="space-y-3">
              {examples.map((example) => (
                <button
                  key={example.id}
                  className="w-full text-left border border-gray-200 rounded-lg p-4 hover:shadow-md hover:border-blue-300 transition-all"
                  onClick={() => {
                    setShowExamplePicker(false);
                    handleLoadExample(example);
                  }}
                >
                  <h4 className="font-medium text-gray-900">{example.title}</h4>
                  <p className="text-sm text-gray-600 mt-1">{example.description}</p>
                  <div className="flex gap-2 mt-2">
                    <span className="inline-flex items-center px-2 py-0.5 rounded text-xs border border-gray-300 bg-gray-50 text-gray-600">
                      {example.nodes.length} nodes
                    </span>
                    <span className="inline-flex items-center px-2 py-0.5 rounded text-xs border border-gray-300 bg-gray-50 text-gray-600">
                      {example.edges.length} edges
                    </span>
                  </div>
                </button>
              ))}
            </div>
            <div className="mt-4 flex justify-end">
              <button
                className="px-4 py-2 text-sm text-gray-600 hover:text-gray-800"
                onClick={() => setShowExamplePicker(false)}
              >
                Cancel
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Confirm Clear Dialog */}
      {confirmClearOpen && (
        <div
          className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50"
          onClick={() => setConfirmClearOpen(false)}
        >
          <div
            className="bg-white rounded-lg p-6 w-full max-w-sm"
            onClick={(e) => e.stopPropagation()}
          >
            <h2 className="text-lg font-semibold mb-2">Clear canvas?</h2>
            <p className="text-sm text-gray-600 mb-6">
              This will remove all nodes and edges. This cannot be undone.
            </p>
            <div className="flex justify-end gap-2">
              <Button outline onClick={() => setConfirmClearOpen(false)}>
                Cancel
              </Button>
              <Button color="red" onClick={handleClearCanvas}>
                Clear
              </Button>
            </div>
          </div>
        </div>
      )}

      {/* Confirm Load Example Dialog */}
      <ConfirmLoadExampleDialog
        open={confirmDialogOpen}
        onClose={handleCancelLoadExample}
        onConfirm={handleConfirmLoadExample}
        exampleTitle={selectedExample?.title || ''}
        hasExistingContent={hasExistingContent}
      />
    </div>
  );
};

export default GraphBuilder;
