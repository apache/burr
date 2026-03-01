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

import { Node, Edge } from '@xyflow/react';

/**
 * Interchange format for Burr graphs. This is the central data model that connects:
 * - Visual graph editing (Graph Builder canvas)
 * - Python code generation (BurrCodeGenerator)
 * - Example loading (ExampleLoader)
 * - Future: Pyodide-based Python AST parsing (code -> visual)
 * - Future: Tracking API import (ApplicationModel -> BurrGraphJSON)
 */
export interface BurrGraphJSON {
  version: string;
  metadata: {
    created: string;
    title?: string;
    description?: string;
  };
  nodes: Array<{
    id: string;
    label: string;
    description?: string;
    nodeType: 'input' | 'action';
    isAsync?: boolean;
    isStreaming?: boolean;
    position: { x: number; y: number };
  }>;
  edges: Array<{
    id: string;
    source: string;
    target: string;
    condition?: string;
    isConditional: boolean;
  }>;
}

export class GraphExporter {
  static exportToJSON(nodes: Node[], edges: Edge[]): BurrGraphJSON {
    return {
      version: '1.0.0',
      metadata: {
        created: new Date().toISOString(),
        title: 'Burr Graph',
        description: 'Generated from Burr Graph Builder'
      },
      nodes: nodes.map((node) => ({
        id: node.id,
        label: (node.data.label as string) || 'Unnamed Node',
        description: (node.data.description as string) || undefined,
        nodeType:
          (node.data.nodeType as string) === 'input' ? ('input' as const) : ('action' as const),
        isAsync: Boolean(node.data.isAsync) || undefined,
        isStreaming: Boolean(node.data.isStreaming) || undefined,
        position: node.position
      })),
      edges: edges.map((edge) => ({
        id: edge.id,
        source: edge.source,
        target: edge.target,
        condition: (edge.data?.label as string) || (edge.data?.condition as string) || undefined,
        isConditional: Boolean(edge.data?.isConditional) || false
      }))
    };
  }
}
