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

import { BurrGraphJSON } from './GraphExporter';

type NodeRef = BurrGraphJSON['nodes'][0];

export class BurrGraphCodeGenerator {
  static generatePythonCode(graphData: BurrGraphJSON): string {
    const actionNodes = graphData.nodes.filter((n) => n.nodeType !== 'input');
    const hasAsync = actionNodes.some((n) => n.isAsync);
    const hasStreaming = actionNodes.some((n) => n.isStreaming);

    const imports = this.generateImports(actionNodes, hasAsync, hasStreaming);
    const actions = this.generateActions(graphData.nodes, graphData.edges);
    const graphFunction = this.generateGraphFunction(graphData);
    const main = this.generateMain(hasAsync, hasStreaming);

    return [imports, actions, graphFunction, main].join('\n\n');
  }

  private static generateImports(
    actionNodes: NodeRef[],
    hasAsync: boolean,
    hasStreaming: boolean
  ): string {
    // Decorator imports
    const decorators: string[] = ['action'];
    if (hasStreaming) decorators.push('streaming_action');
    const actionImports = `from burr.core.action import ${decorators.join(', ')}`;

    // Typing imports
    const typingParts: string[] = ['Tuple'];
    if (hasStreaming) {
      typingParts.push('Optional');
      if (hasAsync) typingParts.push('AsyncGenerator');
      else typingParts.push('Generator');
    }
    const typingImports = `from typing import ${typingParts.join(', ')}`;

    const asyncioImport = hasAsync ? '\nimport asyncio' : '';

    return `${typingImports}
from burr.core import State, default, when
${actionImports}
from burr.core.graph import GraphBuilder${asyncioImport}`;
  }

  private static generateActions(
    nodes: BurrGraphJSON['nodes'],
    edges: BurrGraphJSON['edges']
  ): string {
    const processNodes = nodes.filter((node) => node.nodeType !== 'input');

    const actionFunctions = processNodes.map((node) => {
      return this.generateAction(node, nodes, edges);
    });

    return actionFunctions.join('\n\n');
  }

  private static generateAction(
    node: NodeRef,
    nodes: BurrGraphJSON['nodes'],
    edges: BurrGraphJSON['edges']
  ): string {
    const functionName = this.sanitizeNodeName(node.label);
    const inputParams = this.getInputParameters(node.id, nodes, edges);
    const paramString =
      inputParams.length > 0 ? `state: State, ${inputParams.join(', ')}` : 'state: State';

    const isAsync = node.isAsync || false;
    const isStreaming = node.isStreaming || false;

    const decorator = isStreaming
      ? '@streaming_action(reads=[], writes=[])'
      : '@action(reads=[], writes=[])';
    const asyncKeyword = isAsync ? 'async ' : '';

    let returnType: string;
    let body: string;
    let docKind: string;

    if (isStreaming && isAsync) {
      returnType = 'AsyncGenerator[Tuple[dict, Optional[State]], None]';
      body = '    yield {}, state';
      docKind = 'async streaming action';
    } else if (isStreaming) {
      returnType = 'Generator[Tuple[dict, Optional[State]], None, None]';
      body = '    yield {}, state';
      docKind = 'streaming action';
    } else if (isAsync) {
      returnType = 'Tuple[dict, State]';
      body = '    return {}, state';
      docKind = 'async action';
    } else {
      returnType = 'Tuple[dict, State]';
      body = '    return {}, state';
      docKind = 'action';
    }

    const docstring = node.description
      ? `\n    """${node.description}\n\n    This is a stub ${docKind}. Please complete with your business logic.\n    """`
      : `\n    """Stub ${docKind}. Please complete with your business logic."""`;

    return `${decorator}
${asyncKeyword}def ${functionName}(${paramString}) -> ${returnType}:${docstring}
${body}`;
  }

  private static getInputParameters(
    nodeId: string,
    nodes: BurrGraphJSON['nodes'],
    edges: BurrGraphJSON['edges']
  ): string[] {
    const inputParams: string[] = [];

    edges.forEach((edge) => {
      if (edge.target === nodeId) {
        const sourceNode = nodes.find((n) => n.id === edge.source);
        if (sourceNode && sourceNode.nodeType === 'input') {
          const paramName = sourceNode.label.replace(/^input:\s*/, '').trim();
          const sanitizedParam = this.sanitizeParameterName(paramName);
          inputParams.push(`${sanitizedParam}: str`);
        }
      }
    });

    return inputParams;
  }

  private static sanitizeParameterName(name: string): string {
    return (
      name
        .toLowerCase()
        .replace(/[^a-z0-9]/g, '_')
        .replace(/_+/g, '_')
        .replace(/^_|_$/g, '') || 'param'
    );
  }

  private static deduplicateNames(names: string[]): string[] {
    const seen = new Map<string, number>();
    return names.map((name) => {
      const count = seen.get(name) || 0;
      seen.set(name, count + 1);
      return count > 0 ? `${name}_${count}` : name;
    });
  }

  private static generateGraphFunction(graphData: BurrGraphJSON): string {
    const processNodes = graphData.nodes.filter((node) => node.nodeType !== 'input');
    const actionNames = this.deduplicateNames(
      processNodes.map((node) => this.sanitizeNodeName(node.label))
    );
    const transitions = this.generateTransitions(graphData);

    const actionsString = actionNames.map((name) => `          ${name},`).join('\n');

    return `def create_burr_graph():
    """Create the Burr graph for the project."""
    return (
        GraphBuilder()
        .with_actions(
${actionsString}
        )
        .with_transitions(
${transitions}
        )
        .build()
    )`;
  }

  private static generateTransitions(graphData: BurrGraphJSON): string {
    const transitions: string[] = [];

    const processEdges = graphData.edges.filter((edge) => {
      const sourceNode = graphData.nodes.find((n) => n.id === edge.source);
      const targetNode = graphData.nodes.find((n) => n.id === edge.target);
      return sourceNode?.nodeType !== 'input' && targetNode?.nodeType !== 'input';
    });

    const edgesBySource = new Map<string, typeof processEdges>();
    processEdges.forEach((edge) => {
      if (!edgesBySource.has(edge.source)) {
        edgesBySource.set(edge.source, []);
      }
      edgesBySource.get(edge.source)!.push(edge);
    });

    const allTransitions: Array<{ source: string; target: string; condition: string }> = [];

    edgesBySource.forEach((edges, sourceId) => {
      const sourceNode = graphData.nodes.find((n) => n.id === sourceId);
      if (!sourceNode || sourceNode.nodeType === 'input') return;

      const sourceName = this.sanitizeNodeName(sourceNode.label);

      if (edges.length === 1) {
        const edge = edges[0];
        const targetNode = graphData.nodes.find((n) => n.id === edge.target);
        if (targetNode && targetNode.nodeType !== 'input') {
          const targetName = this.sanitizeNodeName(targetNode.label);
          allTransitions.push({ source: sourceName, target: targetName, condition: 'default' });
        }
      } else {
        const conditionalEdges = edges.filter((e) => e.isConditional && e.condition);
        const defaultEdges = edges.filter((e) => !e.isConditional || !e.condition);

        conditionalEdges.forEach((edge) => {
          const targetNode = graphData.nodes.find((n) => n.id === edge.target);
          if (targetNode && targetNode.nodeType !== 'input' && edge.condition) {
            const targetName = this.sanitizeNodeName(targetNode.label);
            allTransitions.push({
              source: sourceName,
              target: targetName,
              condition: `when(${edge.condition})`
            });
          }
        });

        if (defaultEdges.length > 0) {
          const defaultEdge = defaultEdges[0];
          const targetNode = graphData.nodes.find((n) => n.id === defaultEdge.target);
          if (targetNode && targetNode.nodeType !== 'input') {
            const targetName = this.sanitizeNodeName(targetNode.label);
            allTransitions.push({ source: sourceName, target: targetName, condition: 'default' });
          }
        }
      }
    });

    // Group default transitions by target so multiple sources going to the same
    // target can be collapsed into a single list-form transition.
    const defaultsByTarget = new Map<string, string[]>();
    const conditionalTransitions: Array<{ source: string; target: string; condition: string }> = [];

    allTransitions.forEach(({ source, target, condition }) => {
      if (condition === 'default') {
        if (!defaultsByTarget.has(target)) {
          defaultsByTarget.set(target, []);
        }
        defaultsByTarget.get(target)!.push(source);
      } else {
        conditionalTransitions.push({ source, target, condition });
      }
    });

    // Emit conditional transitions first
    conditionalTransitions.forEach(({ source, target, condition }) => {
      transitions.push(`            ("${source}", "${target}", ${condition}),`);
    });

    // Emit default transitions (possibly grouped)
    defaultsByTarget.forEach((sources, target) => {
      if (sources.length === 1) {
        transitions.push(`            ("${sources[0]}", "${target}", default),`);
      } else {
        const sourceList = sources.map((s) => `                    "${s}"`).join(',\n');
        transitions.push(
          `            (\n                [\n${sourceList}\n                ],\n                "${target}",\n            ),`
        );
      }
    });

    return transitions.join('\n');
  }

  private static generateMain(hasAsync: boolean, hasStreaming: boolean): string {
    const needsAsyncMain = hasAsync || hasStreaming;
    if (needsAsyncMain) {
      return `graph = create_burr_graph()


async def main():
    """Run the Burr application.

    Uses async execution which handles both sync and async actions seamlessly.
    """
    # action_, result, state = await app.arun(halt_after=[...])
    print("Burr graph created successfully.")
    print(graph)


if __name__ == "__main__":
    asyncio.run(main())`;
    }
    return `graph = create_burr_graph()

if __name__ == "__main__":
    print("Burr graph created successfully.")
    print(graph)
    # You can now use \`graph\` in your Burr application.`;
  }

  private static sanitizeNodeName(label: string): string {
    return (
      label
        .toLowerCase()
        .replace(/[^a-z0-9]/g, '_')
        .replace(/_+/g, '_')
        .replace(/^_|_$/g, '') || 'unnamed_node'
    );
  }
}
