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

export type NodeType = 'action' | 'input' | 'result' | 'llm_call' | 'api_call' | 'code' | 'streaming' | 'loop' | 'router';

export const NODE_TYPE_META: Record<
  NodeType,
  { label: string; color: string; borderColor: string; description: string }
> = {
  action: {
    label: 'Action',
    color: 'bg-white',
    borderColor: 'border-gray-300',
    description: 'Generic action with reads/writes'
  },
  input: {
    label: 'Input',
    color: 'bg-green-50',
    borderColor: 'border-green-400',
    description: 'Receives external data into state'
  },
  result: {
    label: 'Result',
    color: 'bg-blue-50',
    borderColor: 'border-blue-400',
    description: 'Extracts output from state'
  },
  llm_call: {
    label: 'LLM Call',
    color: 'bg-purple-50',
    borderColor: 'border-purple-400',
    description: 'Call an LLM with prompt/response'
  },
  api_call: {
    label: 'API Call',
    color: 'bg-orange-50',
    borderColor: 'border-orange-400',
    description: 'HTTP request to external API'
  },
  code: {
    label: 'Code',
    color: 'bg-gray-50',
    borderColor: 'border-gray-500',
    description: 'Custom Python code block'
  },
  streaming: {
    label: 'Streaming',
    color: 'bg-cyan-50',
    borderColor: 'border-cyan-400',
    description: 'Yields results progressively'
  },
  loop: {
    label: 'Loop',
    color: 'bg-amber-50',
    borderColor: 'border-amber-400',
    description: 'Iterate over items in state'
  },
  router: {
    label: 'Router',
    color: 'bg-rose-50',
    borderColor: 'border-rose-400',
    description: 'Branch based on conditions'
  }
};

export type BuilderNode = {
  id: string;
  name: string;
  nodeType: NodeType;
  reads: string[];
  writes: string[];
  inputs: string[];
  position: { x: number; y: number };
  codeBody?: string;
  llmProvider?: string;
  llmModel?: string;
  apiUrl?: string;
  apiMethod?: string;
  // Tree structure
  nextAction?: BuilderNode;
  firstLoopAction?: BuilderNode;
  branches?: BuilderBranch[];
  // Loop config
  loopVariable?: string;
  itemVariable?: string;
};

export type BuilderBranch = {
  name: string;
  condition: string;
  firstAction?: BuilderNode;
};

export type BuilderEdge = {
  id: string;
  source: string;
  target: string;
  condition: string;
};

// Sanitize a string for use as a Python identifier (a-z, 0-9, _)
function sanitizeName(name: string): string {
  return name.replace(/[^a-zA-Z0-9_]/g, '_').replace(/^[0-9]/, '_$&') || 'unnamed';
}

// Escape a string for embedding in Python string literal
function escapePyString(s: string): string {
  return s.replace(/\\/g, '\\\\').replace(/"/g, '\\"').replace(/\n/g, '\\n');
}

const generateActionCode = (node: BuilderNode): string[] => {
  const lines: string[] = [];
  const safeName = sanitizeName(node.name);
  const readsStr = node.reads.map((r) => `"${escapePyString(r)}"`).join(', ');
  const writesStr = node.writes.map((w) => `"${escapePyString(w)}"`).join(', ');

  switch (node.nodeType) {
    case 'input': {
      lines.push(`@action(reads=[], writes=[${writesStr}])`);
      const params = ['state: State', ...node.inputs.map((i) => `${sanitizeName(i)}: str`)];
      lines.push(`def ${safeName}(${params.join(', ')}) -> State:`);
      if (node.writes.length > 0) {
        const updates = node.writes.map((w, i) => `${w}=${node.inputs[i] || 'None'}`).join(', ');
        lines.push(`    return state.update(${updates})`);
      } else {
        lines.push('    return state');
      }
      break;
    }
    case 'result': {
      lines.push(`@action(reads=[${readsStr}], writes=[])`);
      lines.push(`def ${safeName}(state: State) -> State:`);
      if (node.reads.length > 0) {
        lines.push(`    # Output: ${node.reads.join(', ')}`);
      }
      lines.push('    return state');
      break;
    }
    case 'llm_call': {
      const provider = node.llmProvider || 'openai';
      const model = node.llmModel || 'gpt-4';
      lines.push(`@action(reads=[${readsStr}], writes=[${writesStr}])`);
      lines.push(`def ${safeName}(state: State) -> State:`);
      const promptKey = node.reads[0] || 'prompt';
      const responseKey = node.writes[0] || 'response';
      lines.push(`    prompt = state["${promptKey}"]`);
      lines.push(`    # TODO: call ${provider} with model="${model}"`);
      lines.push(`    response = ""`);
      lines.push(`    return state.update(${responseKey}=response)`);
      break;
    }
    case 'api_call': {
      const method = node.apiMethod || 'GET';
      const url = node.apiUrl || 'https://api.example.com';
      lines.push(`@action(reads=[${readsStr}], writes=[${writesStr}])`);
      lines.push(`def ${safeName}(state: State) -> State:`);
      lines.push(`    import requests`);
      lines.push(`    response = requests.${sanitizeName(method).toLowerCase()}("${escapePyString(url)}")`);
      const responseKey = sanitizeName(node.writes[0] || 'response');
      lines.push(`    return state.update(${responseKey}=response.json())`);
      break;
    }
    case 'streaming': {
      lines.push(`@streaming_action(reads=[${readsStr}], writes=[${writesStr}])`);
      lines.push(`def ${safeName}(state: State) -> Generator:`);
      const outKey = node.writes[0] || 'output';
      lines.push(`    result = ""`);
      lines.push(`    for chunk in generate_chunks(state):`);
      lines.push(`        result += chunk`);
      lines.push(`        yield {"${outKey}": chunk}, None`);
      lines.push(`    yield {"${outKey}": result}, state.update(${outKey}=result)`);
      break;
    }
    case 'code': {
      lines.push(`@action(reads=[${readsStr}], writes=[${writesStr}])`);
      const params = ['state: State', ...node.inputs.map((i) => `${i}: str`)];
      lines.push(`def ${safeName}(${params.join(', ')}) -> State:`);
      if (node.codeBody) {
        node.codeBody.split('\n').forEach((line) => lines.push(`    ${line}`));
      } else if (node.writes.length > 0) {
        const updates = node.writes.map((w) => `${w}=None`).join(', ');
        lines.push(`    return state.update(${updates})`);
      } else {
        lines.push('    return state');
      }
      break;
    }
    default: {
      lines.push(`@action(reads=[${readsStr}], writes=[${writesStr}])`);
      const params = ['state: State', ...node.inputs.map((i) => `${i}: str`)];
      lines.push(`def ${safeName}(${params.join(', ')}) -> State:`);
      if (node.writes.length > 0) {
        const updates = node.writes.map((w) => `${w}=None`).join(', ');
        lines.push(`    return state.update(${updates})`);
      } else {
        lines.push('    return state');
      }
    }
  }
  return lines;
};

export const generatePythonCode = (
  nodes: BuilderNode[],
  edges: BuilderEdge[],
  entrypoint: string
): string => {
  const lines: string[] = [];
  const hasStreaming = nodes.some((n) => n.nodeType === 'streaming');
  const hasWhen = edges.some((e) => e.condition.startsWith('when('));
  const hasExpr = edges.some((e) => e.condition.startsWith('expr('));

  const coreImports = ['ApplicationBuilder', 'State', 'action'];
  if (hasStreaming) coreImports.push('streaming_action');
  lines.push(`from burr.core import ${coreImports.join(', ')}`);
  if (hasWhen || hasExpr) {
    const extras = [];
    if (hasWhen) extras.push('when');
    if (hasExpr) extras.push('expr');
    lines.push(`from burr.core import ${extras.join(', ')}`);
  }
  lines.push('');
  lines.push('');

  for (const node of nodes) {
    lines.push(...generateActionCode(node));
    lines.push('');
    lines.push('');
  }

  lines.push('app = (');
  lines.push('    ApplicationBuilder()');

  const actionNames = nodes.map((n) => `${n.name}=${n.name}`).join(', ');
  lines.push(`    .with_actions(${actionNames})`);

  const transitions = edges.map((e) => {
    const cond = !e.condition || e.condition === 'default' ? 'default' : e.condition;
    return `("${e.source}", "${e.target}", ${cond})`;
  });
  if (transitions.length > 0) {
    lines.push(`    .with_transitions(`);
    transitions.forEach((t, i) => {
      lines.push(`        ${t}${i < transitions.length - 1 ? ',' : ''}`);
    });
    lines.push(`    )`);
  }

  lines.push(`    .with_entrypoint("${entrypoint}")`);

  const allKeys = [...new Set(nodes.flatMap((n) => [...n.reads, ...n.writes]))];
  if (allKeys.length > 0) {
    const stateInit = allKeys.map((k) => `${k}=None`).join(', ');
    lines.push(`    .with_state(${stateInit})`);
  }

  lines.push('    .with_tracker(project="my_app")');
  lines.push('    .build()');
  lines.push(')');
  lines.push('');

  return lines.join('\n');
};

export type ProjectFile = {
  name: string;
  language: string;
  content: string;
};

export const generateProjectFiles = (
  nodes: BuilderNode[],
  edges: BuilderEdge[],
  entrypoint: string
): ProjectFile[] => {
  const hasStreaming = nodes.some((n) => n.nodeType === 'streaming');
  const hasApi = nodes.some((n) => n.nodeType === 'api_call');

  // actions.py
  const actionsLines: string[] = [];
  const actionsImports = ['State', 'action'];
  if (hasStreaming) actionsImports.push('streaming_action');
  actionsLines.push(`from burr.core import ${actionsImports.join(', ')}`);
  actionsLines.push('');
  actionsLines.push('');
  for (const node of nodes) {
    actionsLines.push(...generateActionCode(node));
    actionsLines.push('');
    actionsLines.push('');
  }

  // app.py
  const hasWhen = edges.some((e) => e.condition.startsWith('when('));
  const hasExpr = edges.some((e) => e.condition.startsWith('expr('));
  const appLines: string[] = [];
  appLines.push('from burr.core import ApplicationBuilder, default');
  if (hasWhen || hasExpr) {
    const extras = [];
    if (hasWhen) extras.push('when');
    if (hasExpr) extras.push('expr');
    appLines.push(`from burr.core import ${extras.join(', ')}`);
  }
  appLines.push(`from actions import ${nodes.map((n) => n.name).join(', ')}`);
  appLines.push('');
  appLines.push('');
  appLines.push('def build_app():');
  appLines.push('    app = (');
  appLines.push('        ApplicationBuilder()');
  const actionNames = nodes.map((n) => `${n.name}=${n.name}`).join(', ');
  appLines.push(`        .with_actions(${actionNames})`);
  const transitions = edges.map((e) => {
    const cond = !e.condition || e.condition === 'default' ? 'default' : e.condition;
    return `("${e.source}", "${e.target}", ${cond})`;
  });
  if (transitions.length > 0) {
    appLines.push('        .with_transitions(');
    transitions.forEach((t, i) => {
      appLines.push(`            ${t}${i < transitions.length - 1 ? ',' : ''}`);
    });
    appLines.push('        )');
  }
  appLines.push(`        .with_entrypoint("${entrypoint}")`);
  const allKeys = [...new Set(nodes.flatMap((n) => [...n.reads, ...n.writes]))];
  if (allKeys.length > 0) {
    const stateInit = allKeys.map((k) => `${k}=None`).join(', ');
    appLines.push(`        .with_state(${stateInit})`);
  }
  appLines.push('        .with_tracker(project="my_app")');
  appLines.push('        .build()');
  appLines.push('    )');
  appLines.push('    return app');
  appLines.push('');

  // run.py
  const runLines = [
    'from app import build_app',
    '',
    '',
    'if __name__ == "__main__":',
    '    app = build_app()',
    '    app.run(halt_after=["result_1"])',
    '    print("Done! Check the Burr UI for tracking.")',
    ''
  ];

  // requirements.txt
  const deps = ['apache-burr[tracking]'];
  if (hasApi) deps.push('requests');
  const reqContent = deps.join('\n') + '\n';

  return [
    { name: 'actions.py', language: 'python', content: actionsLines.join('\n') },
    { name: 'app.py', language: 'python', content: appLines.join('\n') },
    { name: 'run.py', language: 'python', content: runLines.join('\n') },
    { name: 'requirements.txt', language: 'plaintext', content: reqContent }
  ];
};
