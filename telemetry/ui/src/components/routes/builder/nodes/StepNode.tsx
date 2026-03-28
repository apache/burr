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

import React from 'react';
import { Handle, Position } from '@xyflow/react';
import {
  BoltIcon,
  ArrowDownTrayIcon,
  FlagIcon,
  SparklesIcon,
  GlobeAltIcon,
  CodeBracketIcon,
  SignalIcon,
  ArrowPathIcon,
  ArrowsRightLeftIcon,
  ExclamationTriangleIcon
} from '@heroicons/react/24/outline';
import { NodeType, NODE_TYPE_META } from '../../../../utils/codeGenerator';
import { CANVAS } from '../../../../utils/flowLayout';
import { BurrStepNode } from '../../../../utils/builderTypes';
import { Chip } from '../../../common/chip';

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

const HANDLE_STYLE = { opacity: 0, cursor: 'default' };

const StepNodeComponent = React.memo(
  ({ data }: { data: BurrStepNode['data'] }) => {
    const meta = NODE_TYPE_META[data.nodeType as NodeType] || NODE_TYPE_META.action;
    const Icon = NODE_ICONS[data.nodeType as NodeType] || BoltIcon;

    return (
      <div
        style={{ width: CANVAS.STEP_WIDTH, height: CANVAS.STEP_HEIGHT }}
        className={`rounded-lg border-2 cursor-pointer overflow-hidden transition-all ${meta.color} ${
          data.isSelected ? 'border-purple-500 ring-2 ring-purple-200' : meta.borderColor
        } hover:border-purple-300`}
        onClick={data.onSelect}
      >
        <div className="flex items-center gap-2 h-full px-3">
          <div className={`w-9 h-9 rounded-md flex items-center justify-center shrink-0 ${meta.color} border ${meta.borderColor}`}>
            <Icon className="h-5 w-5 text-gray-600" />
          </div>
          <div className="flex-1 min-w-0 overflow-hidden">
            <div className="flex items-center gap-1">
              <span className="text-sm font-semibold text-gray-800 truncate">{data.name}</span>
              {data.unresolvedReads.length > 0 && (
                <ExclamationTriangleIcon
                  className="h-3.5 w-3.5 text-yellow-500 shrink-0"
                  title={`Unresolved: ${data.unresolvedReads.join(', ')}`}
                />
              )}
            </div>
            <div className="text-[10px] text-gray-400">{meta.label}</div>
            {(data.reads.length > 0 || data.writes.length > 0) && (
              <div className="flex flex-wrap gap-0.5 mt-0.5">
                {data.reads.slice(0, 2).map((r) => (
                  <Chip key={r} label={r} chipType="stateRead" className="!text-[7px] !p-0 !px-1" />
                ))}
                {data.writes.slice(0, 2).map((w) => (
                  <Chip key={w} label={w} chipType="stateWrite" className="!text-[7px] !p-0 !px-1" />
                ))}
                {data.reads.length + data.writes.length > 4 && (
                  <span className="text-[8px] text-gray-400">+{data.reads.length + data.writes.length - 4}</span>
                )}
              </div>
            )}
          </div>
        </div>
        <Handle type="target" position={Position.Top} style={HANDLE_STYLE} />
        <Handle type="source" position={Position.Bottom} style={HANDLE_STYLE} />
      </div>
    );
  }
);

StepNodeComponent.displayName = 'StepNodeComponent';
export { StepNodeComponent };
