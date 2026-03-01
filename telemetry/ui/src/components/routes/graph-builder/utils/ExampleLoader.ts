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

import { Node, Edge, MarkerType } from '@xyflow/react';
import { ExampleGraph } from '../data/examples';

export class ExampleLoader {
  static convertToReactFlow(example: ExampleGraph): { nodes: Node[]; edges: Edge[] } {
    const nodes: Node[] = example.nodes.map((node, index) => ({
      id: node.id,
      type: 'custom',
      position: node.position,
      data: {
        label: node.label,
        description: node.description || '',
        nodeType: node.nodeType,
        isAsync: node.isAsync || false,
        isStreaming: node.isStreaming || false,
        icon: 'settings',
        colorIndex: index % 10
      }
    }));

    const edges: Edge[] = example.edges.map((edge) => ({
      id: edge.id,
      source: edge.source,
      target: edge.target,
      type: 'custom',
      markerEnd: {
        type: MarkerType.ArrowClosed,
        width: 15,
        height: 15,
        color: '#429dbce6'
      },
      data: {
        condition: edge.condition,
        isConditional: edge.isConditional,
        label: edge.condition
      }
    }));

    return { nodes, edges };
  }

  static validateExample(example: ExampleGraph): string[] {
    const errors: string[] = [];

    const nodeIds = new Set(example.nodes.map((n) => n.id));

    example.edges.forEach((edge) => {
      if (!nodeIds.has(edge.source)) {
        errors.push(`Edge ${edge.id} references non-existent source node: ${edge.source}`);
      }
      if (!nodeIds.has(edge.target)) {
        errors.push(`Edge ${edge.id} references non-existent target node: ${edge.target}`);
      }
    });

    const uniqueNodeIds = new Set<string>();
    example.nodes.forEach((node) => {
      if (uniqueNodeIds.has(node.id)) {
        errors.push(`Duplicate node ID: ${node.id}`);
      }
      uniqueNodeIds.add(node.id);
    });

    const uniqueEdgeIds = new Set<string>();
    example.edges.forEach((edge) => {
      if (uniqueEdgeIds.has(edge.id)) {
        errors.push(`Duplicate edge ID: ${edge.id}`);
      }
      uniqueEdgeIds.add(edge.id);
    });

    return errors;
  }
}
