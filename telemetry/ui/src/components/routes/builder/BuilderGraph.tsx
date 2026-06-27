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

import { useEffect, useMemo } from 'react';
import {
  ReactFlow,
  Controls,
  Background,
  ReactFlowProvider,
  useReactFlow
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';

import { BurrNodeType, BurrEdgeType, BurrGraph, BurrStepNode, InsertContext } from '../../../utils/builderTypes';
import { NodeType } from '../../../utils/codeGenerator';

import { StepNodeComponent } from './nodes/StepNode';
import { BigAddButtonComponent } from './nodes/BigAddButton';
import { GraphEndWidgetComponent } from './nodes/GraphEndWidget';
import { LoopReturnNodeComponent } from './nodes/LoopReturnNode';

import { StraightLineEdgeComponent } from './edges/StraightLineEdge';
import { LoopStartEdgeComponent } from './edges/LoopStartEdge';
import { LoopReturnEdgeComponent } from './edges/LoopReturnEdge';
import { RouterStartEdgeComponent } from './edges/RouterStartEdge';
import { RouterEndEdgeComponent } from './edges/RouterEndEdge';

const nodeTypes = {
  [BurrNodeType.STEP]: StepNodeComponent,
  [BurrNodeType.BIG_ADD_BUTTON]: BigAddButtonComponent,
  [BurrNodeType.GRAPH_END]: GraphEndWidgetComponent,
  [BurrNodeType.LOOP_RETURN]: LoopReturnNodeComponent
};

const edgeTypes = {
  [BurrEdgeType.STRAIGHT_LINE]: StraightLineEdgeComponent,
  [BurrEdgeType.LOOP_START]: LoopStartEdgeComponent,
  [BurrEdgeType.LOOP_RETURN]: LoopReturnEdgeComponent,
  [BurrEdgeType.ROUTER_START]: RouterStartEdgeComponent,
  [BurrEdgeType.ROUTER_END]: RouterEndEdgeComponent
};

type BuilderGraphProps = {
  layoutGraph: BurrGraph;
  selectedNodeId: string | null;
  onSelectNode: (id: string | null) => void;
  onInsert: (nodeType: NodeType, ctx: InsertContext) => void;
  unresolvedReads: Map<string, string[]>;
};

const BuilderGraphInner = (props: BuilderGraphProps) => {
  const { fitView } = useReactFlow();

  useEffect(() => {
    const timer = setTimeout(() => fitView({ padding: 0.3 }), 50);
    return () => clearTimeout(timer);
  }, [props.layoutGraph, fitView]);

  const flowNodes = useMemo(() => {
    return props.layoutGraph.nodes.map((node) => {
      if (node.type === BurrNodeType.STEP) {
        const stepData = node.data as BurrStepNode['data'];
        return {
          ...node,
          data: {
            ...stepData,
            isSelected: stepData.stepId === props.selectedNodeId,
            unresolvedReads: props.unresolvedReads.get(stepData.name) || [],
            onSelect: () => props.onSelectNode(stepData.stepId)
          }
        };
      }
      if (node.type === BurrNodeType.BIG_ADD_BUTTON) {
        return {
          ...node,
          data: { ...node.data, onInsert: props.onInsert }
        };
      }
      return node;
    });
  }, [props.layoutGraph.nodes, props.selectedNodeId, props.unresolvedReads, props.onSelectNode]);

  const flowEdges = useMemo(() => {
    return props.layoutGraph.edges.map((edge) => ({
      ...edge,
      data: { ...edge.data, onInsert: props.onInsert }
    }));
  }, [props.layoutGraph.edges, props.onInsert]);

  return (
    <ReactFlow
      nodes={flowNodes}
      edges={flowEdges}
      nodeTypes={nodeTypes}
      edgeTypes={edgeTypes}
      nodesDraggable={false}
      nodesConnectable={false}
      elementsSelectable={true}
      onPaneClick={() => props.onSelectNode(null)}
      fitView
      maxZoom={2}
      minZoom={0.1}
    >
      <Background />
      <Controls position="bottom-right" />
    </ReactFlow>
  );
};

export const BuilderGraph = (props: BuilderGraphProps) => {
  return (
    <ReactFlowProvider>
      <BuilderGraphInner {...props} />
    </ReactFlowProvider>
  );
};
