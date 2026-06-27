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

import { BuilderNode, NodeType } from './codeGenerator';
import { createDefaultNode, resetNodeIdCounter, appendToEnd } from './treeUtils';

type ParsedAction = {
  name: string;
  reads: string[];
  writes: string[];
  inputs: string[];
  nodeType: NodeType;
  body: string;
};

type ParsedTransition = {
  from: string;
  to: string;
  condition: string;
};

type ParseResult = {
  actions: ParsedAction[];
  transitions: ParsedTransition[];
  entrypoint: string;
  error?: string;
};

function parseStringList(raw: string): string[] {
  const matches = raw.match(/"([^"]+)"|'([^']+)'/g);
  if (!matches) return [];
  return matches.map((m) => m.replace(/['"]/g, ''));
}

function detectNodeType(
  name: string,
  reads: string[],
  writes: string[],
  decoratorLine: string,
  body: string
): NodeType {
  if (decoratorLine.includes('streaming_action')) return 'streaming';
  if (name.startsWith('input') || (reads.length === 0 && writes.length > 0 && body.includes('user_input')))
    return 'input';
  if (name.startsWith('result') || (writes.length === 0 && reads.length > 0)) return 'result';
  if (name.includes('llm') || body.includes('openai') || body.includes('anthropic') || body.includes('gpt'))
    return 'llm_call';
  if (name.includes('api') || body.includes('requests.')) return 'api_call';
  if (name.includes('loop')) return 'loop';
  if (name.includes('router') || name.includes('branch')) return 'router';
  return 'action';
}

/** Parse Python source code to extract Burr actions, transitions, and entrypoint using regex. */
export function parsePythonCode(code: string): ParseResult {
  const actions: ParsedAction[] = [];
  const transitions: ParsedTransition[] = [];
  let entrypoint = '';

  try {
    const lines = code.split('\n');

    // Parse @action / @streaming_action decorated functions
    for (let i = 0; i < lines.length; i++) {
      const line = lines[i].trim();
      const decoratorMatch = line.match(
        /^@(?:streaming_)?action\s*\(\s*reads\s*=\s*\[([^\]]*)\]\s*,\s*writes\s*=\s*\[([^\]]*)\]\s*\)/
      );
      if (!decoratorMatch) continue;

      const reads = parseStringList(decoratorMatch[1]);
      const writes = parseStringList(decoratorMatch[2]);

      // Next line should be def
      const defLine = lines[i + 1]?.trim() || '';
      const defMatch = defLine.match(/^def\s+(\w+)\s*\(([^)]*)\)/);
      if (!defMatch) continue;

      const name = defMatch[1];
      const paramsRaw = defMatch[2];

      // Extract inputs (parameters after state: State)
      const inputs: string[] = [];
      const params = paramsRaw.split(',').map((p) => p.trim());
      for (const param of params) {
        if (param.startsWith('state') || param === '') continue;
        const paramName = param.split(':')[0].split('=')[0].trim();
        if (paramName && paramName !== 'state') inputs.push(paramName);
      }

      // Collect function body
      let body = '';
      for (let j = i + 2; j < lines.length; j++) {
        const bodyLine = lines[j];
        if (bodyLine.trim() === '' && lines[j + 1]?.trim() === '') break;
        if (/^[^\s]/.test(bodyLine) && bodyLine.trim() !== '') break;
        body += bodyLine + '\n';
      }

      const nodeType = detectNodeType(name, reads, writes, line, body);
      actions.push({ name, reads, writes, inputs, nodeType, body: body.trim() });
    }

    // Parse .with_transitions(...)
    const transitionPattern = /\(\s*"(\w+)"\s*,\s*"(\w+)"\s*,\s*([^)]+)\)/g;
    let tMatch;
    while ((tMatch = transitionPattern.exec(code)) !== null) {
      transitions.push({
        from: tMatch[1],
        to: tMatch[2],
        condition: tMatch[3].trim()
      });
    }

    // Parse .with_entrypoint("...")
    const entryMatch = code.match(/\.with_entrypoint\(\s*"(\w+)"\s*\)/);
    if (entryMatch) {
      entrypoint = entryMatch[1];
    } else if (actions.length > 0) {
      entrypoint = actions[0].name;
    }
  } catch (e) {
    return { actions: [], transitions: [], entrypoint: '', error: String(e) };
  }

  return { actions, transitions, entrypoint };
}

/** Build a BuilderNode tree from parsed Python code results. */
export function buildTreeFromParsed(parsed: ParseResult): BuilderNode | null {
  if (parsed.actions.length === 0) return null;

  resetNodeIdCounter();

  const nodeMap = new Map<string, BuilderNode>();
  for (const action of parsed.actions) {
    const node = createDefaultNode(action.nodeType);
    node.name = action.name;
    node.reads = action.reads;
    node.writes = action.writes;
    node.inputs = action.inputs;
    if (action.body && action.nodeType === 'code') {
      node.codeBody = action.body
        .split('\n')
        .map((l) => l.replace(/^ {4}/, ''))
        .join('\n');
    }
    nodeMap.set(action.name, node);
  }

  // Build chain from transitions, starting at entrypoint
  const startName = parsed.entrypoint || parsed.actions[0].name;
  if (!nodeMap.has(startName)) return null;

  // Build adjacency from transitions (only forward edges, skip self-loops)
  const forwardEdges = new Map<string, string>();
  for (const t of parsed.transitions) {
    if (!forwardEdges.has(t.from) && t.from !== t.to) {
      forwardEdges.set(t.from, t.to);
    }
  }

  // Chain nodes following transitions
  let root: BuilderNode | null = null;
  const visited = new Set<string>();
  let currentName: string | undefined = startName;

  while (currentName && !visited.has(currentName)) {
    visited.add(currentName);
    const node = nodeMap.get(currentName);
    if (!node) break;
    node.nextAction = undefined;
    root = root ? appendToEnd(root, node) : node;
    currentName = forwardEdges.get(currentName);
  }

  // Append any unvisited nodes at the end
  for (const action of parsed.actions) {
    if (!visited.has(action.name) && nodeMap.has(action.name)) {
      const node = nodeMap.get(action.name)!;
      node.nextAction = undefined;
      root = root ? appendToEnd(root, node) : node;
    }
  }

  return root;
}
