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

import { ActionModel, ApplicationModel, Step } from '../../../api';

import dagre from 'dagre';
import React, { createContext, useCallback, useLayoutEffect, useRef, useState } from 'react';
import ReactFlow, {
  BaseEdge,
  Controls,
  EdgeProps,
  Handle,
  MarkerType,
  Position,
  ReactFlowProvider,
  getBezierPath,
  useNodes,
  useReactFlow
} from 'reactflow';

import 'reactflow/dist/style.css';
import { backgroundColorsForIndex } from './AppView';
import { getActionStatus } from '../../../utils';
import { getSmartEdge } from '@tisoap/react-flow-smart-edge';

const dagreGraph = new dagre.graphlib.Graph();

const dagreOptions = {
  rankdir: 'TB', // Top to bottom layout (equivalent to ELK's UP direction)
  nodesep: 80, // Node separation (equivalent to elk.spacing.nodeNode)
  ranksep: 100, // Rank separation (equivalent to elk.layered.spacing.nodeNodeBetweenLayers)
  marginx: 20,
  marginy: 20
};

type ActionNodeData = {
  action: ActionModel;
  label: string;
};

type InputNodeData = {
  input: string;
  label: string;
};

type NodeData = ActionNodeData | InputNodeData;

type NodeType = {
  id: string;
  type: string;
  data: NodeData;
  position: {
    x: number;
    y: number;
  };
};

type EdgeData = {
  from: string;
  to: string;
  condition: string;
};
type EdgeType = {
  id: string;
  source: string;
  target: string;
  markerEnd: {
    type: MarkerType;
    width: number;
    height: number;
  };
  data: EdgeData;
};

const ActionNode = (props: { data: NodeData }) => {
  const {
    highlightedActions: previousActions,
    hoverAction,
    currentAction
  } = React.useContext(NodeStateProvider);
  const highlightedActions = [currentAction, ...(previousActions || [])].reverse();
  const data = props.data as ActionNodeData;
  const name = data.action.name;
  const indexOfAction = highlightedActions.findIndex(
    (step) => step?.step_start_log.action === data.action.name
  );
  const shouldHighlight = indexOfAction !== -1;
  const step = highlightedActions[indexOfAction];
  const isCurrentAction = currentAction?.step_start_log.action === name;
  const bgColor =
    isCurrentAction && step !== undefined
      ? backgroundColorsForIndex(0, getActionStatus(step))
      : shouldHighlight
        ? 'bg-gray-100'
        : '';
  const opacity = hoverAction?.step_start_log.action === name ? 'opacity-50' : '';
  const additionalClasses = isCurrentAction
    ? 'border-dwlightblue/50 text-white border-2'
    : shouldHighlight
      ? 'border-dwlightblue/50 border-2'
      : 'border-dwlightblue/20 border-2';
  return (
    <>
      <Handle type="target" position={Position.Top} />
      <div
        className={`${bgColor} ${opacity} ${additionalClasses} text-xl font-sans p-4 rounded-md border`}
      >
        {name}
      </div>
      <Handle type="source" position={Position.Bottom} id="a" />
    </>
  );
};

const InputNode = (props: { data: NodeData }) => {
  return (
    <>
      <div className=" text-xl font-sans p-4 rounded-md  bg-white bg-opacity-0">
        {props.data.label}
      </div>
      <Handle type="source" position={Position.Bottom} id="a" className="w-0" />
    </>
  );
};
// TODO -- separate out into different edge types
export const ActionActionEdge = ({
  sourceX,
  sourceY,
  targetX,
  targetY,
  sourcePosition,
  targetPosition,
  markerEnd,
  data
}: EdgeProps) => {
  const nodes = useNodes();
  data = data as EdgeData;
  const { highlightedActions: previousActions, currentAction } =
    React.useContext(NodeStateProvider);
  const allActionsInPath = [...(previousActions || []), ...(currentAction ? [currentAction] : [])];
  const containsFrom = allActionsInPath.some(
    (action) => action.step_start_log.action === data.from
  );
  const containsTo = allActionsInPath.some((action) => action.step_start_log.action === data.to);
  const shouldHighlight = containsFrom && containsTo;
  const getSmartEdgeResponse = getSmartEdge({
    sourcePosition,
    targetPosition,
    sourceX,
    sourceY,
    targetX,
    targetY,
    nodes
  });
  let edgePath = null;
  if (getSmartEdgeResponse !== null) {
    edgePath = getSmartEdgeResponse.svgPathString;
  } else {
    edgePath = getBezierPath({
      sourceX,
      sourceY,
      sourcePosition,
      targetX,
      targetY,
      targetPosition
    })[0];
  }

  const style = {
    markerColor: shouldHighlight ? 'black' : 'gray',
    strokeWidth: shouldHighlight ? 2 : 0.5
  };
  return (
    <>
      <BaseEdge path={edgePath} markerEnd={markerEnd} style={style} label={'test'} />
    </>
  );
};

const getLayoutedElements = (
  nodes: NodeType[],
  edges: EdgeType[],
  options: { [key: string]: string } = {}
) => {
  const isHorizontal = options?.['direction'] === 'LR';
  const direction = isHorizontal ? 'LR' : 'TB';

  // Configure dagre graph
  dagreGraph.setDefaultEdgeLabel(() => ({}));
  dagreGraph.setGraph({
    ...dagreOptions,
    rankdir: direction
  });

  // Add nodes to dagre graph
  nodes.forEach((node) => {
    dagreGraph.setNode(node.id, {
      width: 150,
      height: 100
    });
  });

  // Add edges to dagre graph
  edges.forEach((edge) => {
    dagreGraph.setEdge(edge.source, edge.target);
  });

  // Calculate layout
  dagre.layout(dagreGraph);

  // Apply layout to nodes
  const layoutedNodes = nodes.map((node) => {
    const nodeWithPosition = dagreGraph.node(node.id);
    return {
      ...node,
      targetPosition: isHorizontal ? 'left' : 'top',
      sourcePosition: isHorizontal ? 'right' : 'bottom',
      position: {
        x: nodeWithPosition.x - 75, // Center the node (width/2)
        y: nodeWithPosition.y - 50 // Center the node (height/2)
      }
    };
  });

  // Apply layout to edges
  const layoutedEdges = edges.map((edge) => ({
    ...edge,
    markerEnd: { type: MarkerType.Arrow, width: 20, height: 20 }
  }));

  return Promise.resolve({
    nodes: layoutedNodes,
    edges: layoutedEdges
  });
};

const convertApplicationToGraph = (stateMachine: ApplicationModel): [NodeType[], EdgeType[]] => {
  const shouldDisplayInput = (input: string) => !input.startsWith('__');
  const inputUniqueID = (action: ActionModel, input: string) => `${action.name}:${input}`; // Currently they're distinct by name

  const allActionNodes = stateMachine.actions.map((action) => ({
    id: action.name,
    type: 'action',
    data: { action, label: action.name },
    position: { x: 0, y: 0 }
  }));
  // TODO -- consider displaying optional inputs
  const allInputNodes = stateMachine.actions.flatMap((action) =>
    (action.inputs || []).filter(shouldDisplayInput).map((input) => ({
      id: inputUniqueID(action, input),
      type: 'externalInput',
      data: { input, label: input },
      position: { x: 0, y: 0 }
    }))
  );
  const allInputTransitions = stateMachine.actions.flatMap((action) =>
    (action.inputs || []).filter(shouldDisplayInput).map((input) => ({
      id: `${action.name}:${input}-${action.name}`,
      source: inputUniqueID(action, input),
      target: action.name,
      markerEnd: { type: MarkerType.ArrowClosed, width: 20, height: 20 },
      data: { from: inputUniqueID(action, input), condition: input, to: action.name }
    }))
  );
  const allTransitionEdges = stateMachine.transitions.map((transition) => ({
    id: `${transition.from_}-${transition.to}`,
    source: transition.from_,
    target: transition.to,
    markerEnd: { type: MarkerType.ArrowClosed, width: 20, height: 20 },
    data: { from: transition.from_, to: transition.to, condition: transition.condition }
  }));
  return [
    [...allActionNodes, ...allInputNodes],
    [...allInputTransitions, ...allTransitionEdges]
  ];
};

const nodeTypes = {
  action: ActionNode,
  externalInput: InputNode // if this is "input" it is reserved...
};

const edgeTypes = {
  default: ActionActionEdge
};

type NodeState = {
  highlightedActions: Step[] | undefined; // one for each highlighted action, in order from most recent to least recent
  hoverAction: Step | undefined; // the action currently being hovered over
  currentAction: Step | undefined; // the action currently being viewed
};
const NodeStateProvider = createContext<NodeState>({
  highlightedActions: undefined,
  hoverAction: undefined,
  currentAction: undefined
});

export const _Graph = (props: {
  stateMachine: ApplicationModel;
  currentAction: Step | undefined;
  previousActions: Step[] | undefined;
  hoverAction: Step | undefined;
}) => {
  const [initialNodes, initialEdges] = React.useMemo(() => {
    return convertApplicationToGraph(props.stateMachine);
  }, [props.stateMachine]);

  const [nodes, setNodes] = useState<NodeType[]>([]);
  const [edges, setEdges] = useState<EdgeType[]>([]);

  const { fitView } = useReactFlow();

  const onLayout = useCallback(
    ({ direction = 'TB', useInitialNodes = false }): void => {
      const opts = { direction };
      const ns = useInitialNodes ? initialNodes : nodes;
      const es = useInitialNodes ? initialEdges : edges;

      getLayoutedElements(ns, es, opts).then(({ nodes: layoutedNodes, edges: layoutedEdges }) => {
        setNodes(layoutedNodes);
        setEdges(layoutedEdges);

        window.requestAnimationFrame(() => fitView());
      });
    },
    [nodes, edges]
  );

  useLayoutEffect(() => {
    onLayout({ direction: 'TB', useInitialNodes: true });
  }, []);

  return (
    <NodeStateProvider.Provider
      value={{
        highlightedActions: props.previousActions,
        hoverAction: props.hoverAction,
        currentAction: props.currentAction
      }}
    >
      <div className="h-full w-full relative">
        <ReactFlow
          nodes={nodes}
          edges={edges}
          edgesUpdatable={false}
          nodesDraggable={false}
          nodeTypes={nodeTypes}
          edgeTypes={edgeTypes}
          fitView
          maxZoom={100}
          minZoom={0.1}
        />
        <Controls position="bottom-right" className=" relative" />
      </div>
    </NodeStateProvider.Provider>
  );
};

export const GraphView = (props: {
  stateMachine: ApplicationModel;
  currentAction: Step | undefined;
  highlightedActions: Step[] | undefined;
  hoverAction: Step | undefined;
}) => {
  const parentRef = useRef<HTMLDivElement | null>(null);
  const childRef = useRef<HTMLDivElement | null>(null);

  return (
    <div ref={parentRef} className="h-full w-full flex-1">
      <div ref={childRef} className="h-full w-full">
        <ReactFlowProvider>
          <_Graph
            stateMachine={props.stateMachine}
            currentAction={props.currentAction}
            previousActions={props.highlightedActions}
            hoverAction={props.hoverAction}
          />
        </ReactFlowProvider>
      </div>
    </div>
  );
};
