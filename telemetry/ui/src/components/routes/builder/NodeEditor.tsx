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

import { useState } from 'react';
import { BuilderNode, NodeType, NODE_TYPE_META } from '../../../utils/codeGenerator';
import { TrashIcon } from '@heroicons/react/24/outline';

const TagInput = (props: {
  label: string;
  values: string[];
  onChange: (values: string[]) => void;
  colorClass: string;
}) => {
  const [input, setInput] = useState('');

  const addTag = () => {
    const trimmed = input.trim();
    if (trimmed && !props.values.includes(trimmed)) {
      props.onChange([...props.values, trimmed]);
      setInput('');
    }
  };

  return (
    <div className="flex flex-col gap-1">
      <label className="text-xs font-semibold text-gray-500">{props.label}</label>
      <div className="flex flex-wrap gap-1 mb-1">
        {props.values.map((v) => (
          <span
            key={v}
            className={`${props.colorClass} text-white text-xs px-2 py-0.5 rounded-md flex items-center gap-1`}
          >
            {v}
            <button
              className="hover:text-red-200 text-[10px]"
              onClick={() => props.onChange(props.values.filter((x) => x !== v))}
            >
              x
            </button>
          </span>
        ))}
      </div>
      <input
        type="text"
        value={input}
        onChange={(e) => setInput(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter') {
            e.preventDefault();
            addTag();
          }
        }}
        placeholder={`Add ${props.label.toLowerCase()}...`}
        className="border border-gray-200 rounded px-2 py-1 text-sm"
      />
    </div>
  );
};

const TextInput = (props: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  mono?: boolean;
}) => (
  <div className="flex flex-col gap-1">
    <label className="text-xs font-semibold text-gray-500">{props.label}</label>
    <input
      type="text"
      value={props.value}
      onChange={(e) => props.onChange(e.target.value)}
      placeholder={props.placeholder}
      className={`border border-gray-200 rounded px-2 py-1 text-sm ${props.mono ? 'font-mono' : ''}`}
    />
  </div>
);

const SelectInput = (props: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  options: { value: string; label: string }[];
}) => (
  <div className="flex flex-col gap-1">
    <label className="text-xs font-semibold text-gray-500">{props.label}</label>
    <select
      value={props.value}
      onChange={(e) => props.onChange(e.target.value)}
      className="border border-gray-200 rounded px-2 py-1 text-sm bg-white"
    >
      {props.options.map((o) => (
        <option key={o.value} value={o.value}>
          {o.label}
        </option>
      ))}
    </select>
  </div>
);

const CodeInput = (props: { label: string; value: string; onChange: (v: string) => void }) => (
  <div className="flex flex-col gap-1">
    <label className="text-xs font-semibold text-gray-500">{props.label}</label>
    <textarea
      value={props.value}
      onChange={(e) => props.onChange(e.target.value)}
      rows={8}
      placeholder="# Python code here..."
      className="border border-gray-200 rounded px-2 py-1 text-sm font-mono bg-gray-50"
      spellCheck={false}
    />
  </div>
);

const TypeSpecificEditor = (props: {
  node: BuilderNode;
  onUpdate: (updates: Partial<BuilderNode>) => void;
}) => {
  const { node, onUpdate } = props;

  switch (node.nodeType) {
    case 'llm_call':
      return (
        <>
          <SelectInput
            label="Provider"
            value={node.llmProvider || 'openai'}
            onChange={(v) => onUpdate({ llmProvider: v })}
            options={[
              { value: 'openai', label: 'OpenAI' },
              { value: 'anthropic', label: 'Anthropic' },
              { value: 'google', label: 'Google' },
              { value: 'local', label: 'Local / Ollama' }
            ]}
          />
          <TextInput
            label="Model"
            value={node.llmModel || ''}
            onChange={(v) => onUpdate({ llmModel: v })}
            placeholder="gpt-4, claude-3, etc."
          />
        </>
      );

    case 'api_call':
      return (
        <>
          <TextInput
            label="URL"
            value={node.apiUrl || ''}
            onChange={(v) => onUpdate({ apiUrl: v })}
            placeholder="https://api.example.com/endpoint"
            mono
          />
          <SelectInput
            label="Method"
            value={node.apiMethod || 'GET'}
            onChange={(v) => onUpdate({ apiMethod: v })}
            options={[
              { value: 'GET', label: 'GET' },
              { value: 'POST', label: 'POST' },
              { value: 'PUT', label: 'PUT' },
              { value: 'DELETE', label: 'DELETE' },
              { value: 'PATCH', label: 'PATCH' }
            ]}
          />
        </>
      );

    case 'code':
      return (
        <CodeInput
          label="Implementation"
          value={node.codeBody || ''}
          onChange={(v) => onUpdate({ codeBody: v })}
        />
      );

    case 'loop':
      return (
        <>
          <TextInput
            label="Loop Variable (state key)"
            value={node.loopVariable || ''}
            onChange={(v) => onUpdate({ loopVariable: v })}
            placeholder="items"
            mono
          />
          <TextInput
            label="Item Variable"
            value={node.itemVariable || ''}
            onChange={(v) => onUpdate({ itemVariable: v })}
            placeholder="current_item"
            mono
          />
        </>
      );

    case 'router':
      return (
        <div className="flex flex-col gap-2">
          <label className="text-xs font-semibold text-gray-500">Branches</label>
          {(node.branches || []).map((branch, i) => (
            <div key={i} className="flex flex-col gap-1 p-2 bg-gray-50 rounded border border-gray-200">
              <div className="flex items-center justify-between">
                <span className="text-xs font-medium text-gray-600">{branch.name}</span>
                <button
                  className="text-[10px] text-red-400 hover:text-red-600"
                  onClick={() => {
                    const branches = [...(node.branches || [])];
                    branches.splice(i, 1);
                    onUpdate({ branches });
                  }}
                >
                  remove
                </button>
              </div>
              <input
                type="text"
                value={branch.name}
                onChange={(e) => {
                  const branches = [...(node.branches || [])];
                  branches[i] = { ...branches[i], name: e.target.value };
                  onUpdate({ branches });
                }}
                className="border border-gray-200 rounded px-2 py-0.5 text-xs"
                placeholder="Branch name"
              />
              <input
                type="text"
                value={branch.condition}
                onChange={(e) => {
                  const branches = [...(node.branches || [])];
                  branches[i] = { ...branches[i], condition: e.target.value };
                  onUpdate({ branches });
                }}
                className="border border-gray-200 rounded px-2 py-0.5 text-xs font-mono"
                placeholder='default, when(status="ok"), expr("x > 5")'
              />
            </div>
          ))}
          <button
            onClick={() => {
              const branches = [...(node.branches || [])];
              branches.push({ name: `Branch ${branches.length + 1}`, condition: 'default', firstAction: undefined });
              onUpdate({ branches });
            }}
            className="text-xs text-blue-600 hover:text-blue-800 self-start"
          >
            + Add Branch
          </button>
        </div>
      );

    default:
      return null;
  }
};

export const NodeEditor = (props: {
  node: BuilderNode;
  onUpdate: (updates: Partial<BuilderNode>) => void;
  onDelete: () => void;
  unresolvedReads: string[];
}) => {
  const meta = NODE_TYPE_META[props.node.nodeType];

  return (
    <div className="flex flex-col gap-3 p-4 border-l bg-white h-full overflow-y-auto w-80">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span
            className={`text-xs font-medium px-2 py-0.5 rounded ${meta.color} ${meta.borderColor} border`}
          >
            {meta.label}
          </span>
          <h3 className="text-sm font-semibold text-gray-700">Edit Node</h3>
        </div>
        <button
          onClick={props.onDelete}
          className="p-1 text-red-400 hover:text-red-600 rounded"
          title="Delete node"
        >
          <TrashIcon className="h-4 w-4" />
        </button>
      </div>

      <TextInput
        label="Name"
        value={props.node.name}
        onChange={(v) => props.onUpdate({ name: v })}
        placeholder="action_name"
        mono
      />

      <SelectInput
        label="Type"
        value={props.node.nodeType}
        onChange={(v) => props.onUpdate({ nodeType: v as NodeType })}
        options={Object.entries(NODE_TYPE_META).map(([key, m]) => ({
          value: key,
          label: `${m.label} - ${m.description}`
        }))}
      />

      <hr className="border-gray-100" />

      <TypeSpecificEditor node={props.node} onUpdate={props.onUpdate} />

      <TagInput
        label="Reads"
        values={props.node.reads}
        onChange={(reads) => props.onUpdate({ reads })}
        colorClass="bg-dwdarkblue"
      />

      <TagInput
        label="Writes"
        values={props.node.writes}
        onChange={(writes) => props.onUpdate({ writes })}
        colorClass="bg-dwred"
      />

      {(props.node.nodeType === 'action' ||
        props.node.nodeType === 'input' ||
        props.node.nodeType === 'code') && (
        <TagInput
          label="Inputs"
          values={props.node.inputs}
          onChange={(inputs) => props.onUpdate({ inputs })}
          colorClass="bg-yellow-500"
        />
      )}

      {props.unresolvedReads.length > 0 && (
        <div className="bg-yellow-50 border border-yellow-200 rounded p-2 text-xs text-yellow-700">
          <strong>Warning:</strong> No upstream node writes:{' '}
          {props.unresolvedReads.join(', ')}
        </div>
      )}
    </div>
  );
};
