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

import { BuilderNode } from './codeGenerator';
import {
  BurrNodeType,
  BurrEdgeType,
  BurrGraph,
  BurrEdge,
  BurrStepNode,
  BurrGraphEndNode,
  BurrStraightLineEdge,
  BurrBigAddButtonNode,
  BurrLoopReturnNode,
  InsertLocation
} from './builderTypes';

// Canvas constants (matching Activepieces proportions)
export const CANVAS = {
  STEP_WIDTH: 220,
  STEP_HEIGHT: 80,
  VSPACE: 60,
  HSPACE: 80,
  ARC: 15,
  ADD_BUTTON_SIZE: 20,
  BIG_ADD_BUTTON_SIZE: 50,
  LOOP_VOFFSET: 120,
  ROUTER_VOFFSET: 150,
  LINE_WIDTH: 1.5,
  STEP_LINE_GAP: 7
} as const;

// SVG arc path segments
export const ARC_LEFT = `a${CANVAS.ARC},${CANVAS.ARC} 0 0,0 -${CANVAS.ARC},${CANVAS.ARC}`;
export const ARC_RIGHT = `a${CANVAS.ARC},${CANVAS.ARC} 0 0,1 ${CANVAS.ARC},${CANVAS.ARC}`;
export const ARC_LEFT_DOWN = `a${CANVAS.ARC},${CANVAS.ARC} 0 0,1 -${CANVAS.ARC},${CANVAS.ARC}`;
export const ARC_RIGHT_DOWN = `a${CANVAS.ARC},${CANVAS.ARC} 0 0,0 ${CANVAS.ARC},${CANVAS.ARC}`;
export const ARC_RIGHT_UP = `a${CANVAS.ARC},${CANVAS.ARC} 0 0,1 -${CANVAS.ARC},-${CANVAS.ARC}`;
export const ARC_LEFT_UP = `a-${CANVAS.ARC},-${CANVAS.ARC} 0 0,0 ${CANVAS.ARC},-${CANVAS.ARC}`;
export const ARROW_DOWN = 'm6 -6 l-6 6 m-6 -6 l6 6';

type BoundingBox = {
  width: number;
  height: number;
  left: number;
  right: number;
};

function doesAffectBoundingBox(type: string): boolean {
  return (
    type === BurrNodeType.STEP ||
    type === BurrNodeType.BIG_ADD_BUTTON ||
    type === BurrNodeType.LOOP_RETURN
  );
}

export function calculateBoundingBox(graph: BurrGraph): BoundingBox {
  if (graph.nodes.length === 0) {
    return { width: CANVAS.STEP_WIDTH, height: 0, left: CANVAS.STEP_WIDTH / 2, right: CANVAS.STEP_WIDTH / 2 };
  }
  const affectingNodes = graph.nodes.filter((n) => doesAffectBoundingBox(n.type));
  if (affectingNodes.length === 0) {
    // Only GRAPH_END nodes exist; use all nodes for bounds
    const ys = graph.nodes.map((n) => n.position.y);
    return {
      width: CANVAS.STEP_WIDTH,
      height: Math.max(...ys) - Math.min(...ys),
      left: CANVAS.STEP_WIDTH / 2,
      right: CANVAS.STEP_WIDTH / 2
    };
  }
  const minX = Math.min(...affectingNodes.map((n) => n.position.x));
  const maxX = Math.max(...affectingNodes.map((n) => n.position.x + CANVAS.STEP_WIDTH));
  const allYs = graph.nodes.map((n) => n.position.y);
  const maxY = Math.max(...allYs);
  const minY = Math.min(...allYs);
  return {
    width: maxX - minX,
    height: maxY - minY,
    left: -minX + CANVAS.STEP_WIDTH / 2,
    right: maxX - CANVAS.STEP_WIDTH / 2
  };
}

export function offsetGraph(graph: BurrGraph, offset: { x: number; y: number }): BurrGraph {
  return {
    nodes: graph.nodes.map((node) => ({
      ...node,
      position: { x: node.position.x + offset.x, y: node.position.y + offset.y }
    })),
    edges: [...graph.edges]
  };
}

export function mergeGraph(g1: BurrGraph, g2: BurrGraph): BurrGraph {
  return {
    nodes: [...g1.nodes, ...g2.nodes],
    edges: [...g1.edges, ...g2.edges]
  };
}

function createStepGraph(step: BuilderNode, graphHeight: number): BurrGraph {
  const stepNode: BurrStepNode = {
    id: step.id,
    type: BurrNodeType.STEP,
    position: { x: 0, y: 0 },
    data: {
      stepId: step.id,
      name: step.name,
      nodeType: step.nodeType,
      reads: step.reads,
      writes: step.writes,
      inputs: step.inputs,
      unresolvedReads: [],
      isSelected: false,
      onSelect: () => {}
    },
    selectable: true,
    draggable: false
  };

  const graphEndNode: BurrGraphEndNode = {
    id: `${step.id}-subgraph-end`,
    type: BurrNodeType.GRAPH_END,
    position: { x: CANVAS.STEP_WIDTH / 2, y: graphHeight },
    data: {},
    selectable: false
  };

  const isCompound = step.nodeType === 'loop' || step.nodeType === 'router';

  const edges: BurrEdge[] = isCompound
    ? []
    : [
        {
          id: `${step.id}-to-end`,
          source: step.id,
          target: `${step.id}-subgraph-end`,
          type: BurrEdgeType.STRAIGHT_LINE,
          data: {
            drawArrowHead: !!step.nextAction,
            parentStepId: step.id
          }
        } as BurrStraightLineEdge
      ];

  return { nodes: [stepNode, graphEndNode], edges };
}

function createBigAddButtonGraph(
  parentStep: BuilderNode,
  insertCtx: BurrBigAddButtonNode['data']
): BurrGraph {
  const bigButton: BurrBigAddButtonNode = {
    id: `${parentStep.id}-big-add-${insertCtx.edgeId}`,
    type: BurrNodeType.BIG_ADD_BUTTON,
    position: { x: 0, y: 0 },
    data: insertCtx,
    selectable: false
  };

  const endNode: BurrGraphEndNode = {
    id: `${parentStep.id}-subgraph-bigadd-end-${insertCtx.edgeId}`,
    type: BurrNodeType.GRAPH_END,
    position: { x: CANVAS.STEP_WIDTH / 2, y: CANVAS.STEP_HEIGHT + CANVAS.VSPACE },
    data: {},
    selectable: false
  };

  const edge: BurrStraightLineEdge = {
    id: `big-button-line-${insertCtx.edgeId}`,
    source: bigButton.id,
    target: endNode.id,
    type: BurrEdgeType.STRAIGHT_LINE,
    data: { drawArrowHead: false, hideAddButton: true, parentStepId: parentStep.id }
  };

  return { nodes: [bigButton, endNode], edges: [edge] };
}

function buildLoopChildGraph(step: BuilderNode): BurrGraph {
  const childGraph = step.firstLoopAction
    ? buildFlowGraph(step.firstLoopAction)
    : createBigAddButtonGraph(step, {
        location: InsertLocation.INSIDE_LOOP,
        loopStepId: step.id,
        edgeId: `${step.id}-loop-start-edge`
      });

  const childBBox = calculateBoundingBox(childGraph);
  const deltaLeftX =
    -(childBBox.width + CANVAS.STEP_WIDTH + CANVAS.HSPACE - CANVAS.STEP_WIDTH / 2 - childBBox.right) / 2 -
    CANVAS.STEP_WIDTH / 2;

  const loopReturnNode: BurrLoopReturnNode = {
    id: `${step.id}-loop-return-node`,
    type: BurrNodeType.LOOP_RETURN,
    position: {
      x: deltaLeftX + CANVAS.STEP_WIDTH / 2,
      y: CANVAS.STEP_HEIGHT + CANVAS.LOOP_VOFFSET + childBBox.height / 2
    },
    data: {},
    selectable: false
  };

  const childGraphOffset = offsetGraph(childGraph, {
    x: deltaLeftX + CANVAS.STEP_WIDTH + CANVAS.HSPACE + childBBox.left,
    y: CANVAS.LOOP_VOFFSET + CANVAS.STEP_HEIGHT
  });

  const edges: BurrEdge[] = [
    {
      id: `${step.id}-loop-start-edge`,
      source: step.id,
      target: childGraph.nodes[0].id,
      type: BurrEdgeType.LOOP_START,
      data: {
        isLoopEmpty: !step.firstLoopAction,
        parentStepId: step.id
      }
    },
    {
      id: `${step.id}-loop-return-edge`,
      source: childGraph.nodes[childGraph.nodes.length - 1].id,
      target: `${step.id}-loop-return-node`,
      type: BurrEdgeType.LOOP_RETURN,
      data: {
        parentStepId: step.id,
        isLoopEmpty: !step.firstLoopAction,
        drawArrowHeadAfterEnd: !!step.nextAction,
        verticalSpaceBetweenReturnNodeStartAndEnd: childBBox.height + CANVAS.VSPACE
      }
    }
  ];

  const subgraphEnd: BurrGraphEndNode = {
    id: `${step.id}-loop-subgraph-end`,
    type: BurrNodeType.GRAPH_END,
    position: {
      x: CANVAS.STEP_WIDTH / 2,
      y: CANVAS.STEP_HEIGHT + CANVAS.LOOP_VOFFSET + childBBox.height + CANVAS.ARC + CANVAS.VSPACE
    },
    data: {},
    selectable: false
  };

  return {
    nodes: [loopReturnNode, ...childGraphOffset.nodes, subgraphEnd],
    edges: [...edges, ...childGraphOffset.edges]
  };
}

function buildRouterChildGraph(step: BuilderNode): BurrGraph {
  const branches = step.branches || [];

  const childGraphs = branches.map((branch, index) => {
    return branch.firstAction
      ? buildFlowGraph(branch.firstAction)
      : createBigAddButtonGraph(step, {
          location: InsertLocation.INSIDE_BRANCH,
          routerStepId: step.id,
          branchIndex: index,
          edgeId: `${step.id}-branch-${index}-start-edge`
        });
  });

  if (childGraphs.length === 0) {
    return { nodes: [], edges: [] };
  }

  const childGraphsOffset = offsetRouterChildSteps(childGraphs);

  const maxHeight = Math.max(...childGraphsOffset.map((cg) => calculateBoundingBox(cg).height));

  const subgraphEnd: BurrGraphEndNode = {
    id: `${step.id}-branch-subgraph-end`,
    type: BurrNodeType.GRAPH_END,
    position: {
      x: CANVAS.STEP_WIDTH / 2,
      y: CANVAS.STEP_HEIGHT + CANVAS.ROUTER_VOFFSET + maxHeight + CANVAS.ARC + CANVAS.VSPACE
    },
    data: {},
    selectable: false
  };

  const edges: BurrEdge[] = childGraphsOffset
    .map((childGraph, branchIndex) => {
      const branchData = branches[branchIndex];
      return [
        {
          id: `${step.id}-branch-${branchIndex}-start-edge`,
          source: step.id,
          target: childGraph.nodes[0].id,
          type: BurrEdgeType.ROUTER_START,
          data: {
            isBranchEmpty: !branchData.firstAction,
            label: branchData.name,
            branchIndex,
            drawHorizontalLine: branchIndex === 0 || branchIndex === childGraphsOffset.length - 1,
            drawStartingVerticalLine: branchIndex === 0,
            parentStepId: step.id
          }
        },
        {
          id: `${step.id}-branch-${branchIndex}-end-edge`,
          source: childGraph.nodes[childGraph.nodes.length - 1].id,
          target: subgraphEnd.id,
          type: BurrEdgeType.ROUTER_END,
          data: {
            drawEndingVerticalLine: branchIndex === 0,
            verticalSpaceBetweenLastNodeInBranchAndEndLine:
              subgraphEnd.position.y -
              childGraph.nodes[childGraph.nodes.length - 1].position.y -
              CANVAS.VSPACE -
              CANVAS.ARC,
            drawHorizontalLine: branchIndex === 0 || branchIndex === childGraphsOffset.length - 1,
            routerStepId: step.id,
            isNextStepEmpty: !step.nextAction
          }
        }
      ];
    })
    .flat() as BurrEdge[];

  return {
    nodes: [...childGraphsOffset.flatMap((cg) => cg.nodes), subgraphEnd],
    edges: [...childGraphsOffset.flatMap((cg) => cg.edges), ...edges]
  };
}

function offsetRouterChildSteps(childGraphs: BurrGraph[]): BurrGraph[] {
  const bboxes = childGraphs.map((g) => calculateBoundingBox(g));
  const totalWidth =
    bboxes.reduce((acc, b) => acc + b.width, 0) + CANVAS.HSPACE * (childGraphs.length - 1);

  let deltaLeftX = -(totalWidth - bboxes[0].left - bboxes[bboxes.length - 1].right) / 2 - bboxes[0].left;

  return bboxes.map((bbox, index) => {
    const x = deltaLeftX + bbox.left;
    deltaLeftX += bbox.width + CANVAS.HSPACE;
    return offsetGraph(childGraphs[index], {
      x,
      y: CANVAS.STEP_HEIGHT + CANVAS.ROUTER_VOFFSET
    });
  });
}

export function buildFlowGraph(step: BuilderNode | undefined): BurrGraph {
  if (!step) return { nodes: [], edges: [] };

  const graph = createStepGraph(step, CANVAS.STEP_HEIGHT + CANVAS.VSPACE);

  const childGraph =
    step.nodeType === 'loop'
      ? buildLoopChildGraph(step)
      : step.nodeType === 'router'
        ? buildRouterChildGraph(step)
        : null;

  const graphWithChild = childGraph ? mergeGraph(graph, childGraph) : graph;

  const nextStepGraph = buildFlowGraph(step.nextAction);
  return mergeGraph(
    graphWithChild,
    offsetGraph(nextStepGraph, { x: 0, y: calculateBoundingBox(graphWithChild).height })
  );
}
