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

import { Handle, Position } from '@xyflow/react';
import { Chip } from '../../common/chip';
import {
  ExclamationTriangleIcon,
  BoltIcon,
  ArrowDownTrayIcon,
  FlagIcon,
  SparklesIcon,
  GlobeAltIcon,
  CodeBracketIcon,
  SignalIcon,
  ArrowPathIcon,
  ArrowsRightLeftIcon
} from '@heroicons/react/24/outline';
import { NodeType, NODE_TYPE_META } from '../../../utils/codeGenerator';

// eslint-disable-next-line @typescript-eslint/no-explicit-any
const NODE_ICONS: Record<NodeType, React.ComponentType<any>> = {
  action: BoltIcon,
  input: ArrowDownTrayIcon,
  result: FlagIcon,
  llm_call: SparklesIcon,
  api_call: GlobeAltIcon,
  code: CodeBracketIcon,
  streaming: SignalIcon,
  loop: ArrowPathIcon,
  router: ArrowsRightLeftIcon
};

type BuilderNodeData = {
  label: string;
  nodeType: NodeType;
  reads: string[];
  writes: string[];
  inputs: string[];
  isSelected: boolean;
  unresolvedReads: string[];
  onSelect: () => void;
};

export const BuilderNodeComponent = (props: { data: BuilderNodeData }) => {
  const { label, nodeType, reads, writes, inputs, isSelected, unresolvedReads, onSelect } =
    props.data;
  const meta = NODE_TYPE_META[nodeType];
  const Icon = NODE_ICONS[nodeType];

  return (
    <>
      <Handle type="target" position={Position.Top} />
      <div
        className={`p-3 rounded-lg border-2 cursor-pointer min-w-[160px] shadow-sm ${meta.color} ${
          isSelected ? 'border-purple-500 ring-2 ring-purple-200' : meta.borderColor
        }`}
        onClick={onSelect}
      >
        <div className="flex items-center gap-1.5 mb-1">
          <Icon className="h-4 w-4 text-gray-500 shrink-0" />
          <span className="font-semibold text-sm">{label}</span>
          <span className="text-[9px] text-gray-400 ml-auto">{meta.label}</span>
          {unresolvedReads.length > 0 && (
            <ExclamationTriangleIcon
              className="h-4 w-4 text-yellow-500"
              title={`Unresolved: ${unresolvedReads.join(', ')}`}
            />
          )}
        </div>

        {reads.length > 0 && (
          <div className="flex flex-wrap gap-0.5 mb-0.5">
            {reads.map((r) => (
              <Chip key={r} label={r} chipType="stateRead" className="!text-[8px] !p-0.5 !px-1" />
            ))}
          </div>
        )}
        {writes.length > 0 && (
          <div className="flex flex-wrap gap-0.5 mb-0.5">
            {writes.map((w) => (
              <Chip key={w} label={w} chipType="stateWrite" className="!text-[8px] !p-0.5 !px-1" />
            ))}
          </div>
        )}
        {inputs.length > 0 && (
          <div className="flex flex-wrap gap-0.5">
            {inputs.map((i) => (
              <Chip key={i} label={i} chipType="input" className="!text-[8px] !p-0.5 !px-1" />
            ))}
          </div>
        )}
      </div>
      <Handle type="source" position={Position.Bottom} id="a" />
    </>
  );
};
