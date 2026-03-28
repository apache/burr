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

import { Edge } from '@xyflow/react';

/** ReactFlow node types used in the builder canvas. */
export enum BurrNodeType {
  STEP = 'STEP',
  BIG_ADD_BUTTON = 'BIG_ADD_BUTTON',
  GRAPH_END = 'GRAPH_END',
  LOOP_RETURN = 'LOOP_RETURN',
}

/** ReactFlow edge types used in the builder canvas. */
export enum BurrEdgeType {
  STRAIGHT_LINE = 'BurrStraightLine',
  LOOP_START = 'BurrLoopStart',
  LOOP_RETURN = 'BurrLoopReturn',
  ROUTER_START = 'BurrRouterStart',
  ROUTER_END = 'BurrRouterEnd',
}

/** Where a new node should be inserted relative to existing nodes. */
export enum InsertLocation {
  AFTER = 'AFTER',
  INSIDE_LOOP = 'INSIDE_LOOP',
  INSIDE_BRANCH = 'INSIDE_BRANCH',
}

/** Context passed to the inline add button, describing where to insert a new node. */
export type InsertContext =
  | { location: InsertLocation.AFTER; parentStepId: string }
  | { location: InsertLocation.INSIDE_LOOP; loopStepId: string }
  | { location: InsertLocation.INSIDE_BRANCH; routerStepId: string; branchIndex: number };

// Layout graph types (output of flowLayout, input to ReactFlow)

export type BurrStepNode = {
  id: string;
  type: BurrNodeType.STEP;
  position: { x: number; y: number };
  data: {
    stepId: string;
    name: string;
    nodeType: string;
    reads: string[];
    writes: string[];
    inputs: string[];
    unresolvedReads: string[];
    isSelected: boolean;
    onSelect: () => void;
  };
  selectable?: boolean;
  draggable?: boolean;
};

export type BurrBigAddButtonNode = {
  id: string;
  type: BurrNodeType.BIG_ADD_BUTTON;
  position: { x: number; y: number };
  data: InsertContext & { edgeId: string };
  selectable?: boolean;
};

export type BurrGraphEndNode = {
  id: string;
  type: BurrNodeType.GRAPH_END;
  position: { x: number; y: number };
  data: { showWidget?: boolean };
  selectable?: boolean;
};

export type BurrLoopReturnNode = {
  id: string;
  type: BurrNodeType.LOOP_RETURN;
  position: { x: number; y: number };
  data: Record<string, never>;
  selectable?: boolean;
};

export type BurrNode =
  | BurrStepNode
  | BurrBigAddButtonNode
  | BurrGraphEndNode
  | BurrLoopReturnNode;

export type BurrStraightLineEdge = Edge & {
  type: BurrEdgeType.STRAIGHT_LINE;
  data: {
    drawArrowHead: boolean;
    hideAddButton?: boolean;
    parentStepId: string;
  };
};

export type BurrLoopStartEdge = Edge & {
  type: BurrEdgeType.LOOP_START;
  data: {
    isLoopEmpty: boolean;
    parentStepId: string;
  };
};

export type BurrLoopReturnEdge = Edge & {
  type: BurrEdgeType.LOOP_RETURN;
  data: {
    parentStepId: string;
    isLoopEmpty: boolean;
    drawArrowHeadAfterEnd: boolean;
    verticalSpaceBetweenReturnNodeStartAndEnd: number;
  };
};

export type BurrRouterStartEdge = Edge & {
  type: BurrEdgeType.ROUTER_START;
  data: {
    isBranchEmpty: boolean;
    label: string;
    branchIndex: number;
    drawHorizontalLine: boolean;
    drawStartingVerticalLine: boolean;
    parentStepId: string;
  };
};

export type BurrRouterEndEdge = Edge & {
  type: BurrEdgeType.ROUTER_END;
  data: {
    drawHorizontalLine: boolean;
    verticalSpaceBetweenLastNodeInBranchAndEndLine: number;
    drawEndingVerticalLine: boolean;
    routerStepId?: string;
    isNextStepEmpty?: boolean;
  };
};

export type BurrEdge =
  | BurrStraightLineEdge
  | BurrLoopStartEdge
  | BurrLoopReturnEdge
  | BurrRouterStartEdge
  | BurrRouterEndEdge;

/** A complete layout graph with positioned nodes and typed edges, ready for ReactFlow. */
export type BurrGraph = {
  nodes: BurrNode[];
  edges: BurrEdge[];
};
