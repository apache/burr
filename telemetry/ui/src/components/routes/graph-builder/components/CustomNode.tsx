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

import React, { memo, useState, useCallback, useRef, useEffect } from 'react';
import { Handle, Position, NodeProps, Node } from '@xyflow/react';

const pastelColors = [
  { border: '#FF6B6B', background: '#FFE5E5' },
  { border: '#4ECDC4', background: '#E5F9F6' },
  { border: '#45B7D1', background: '#E5F4FD' },
  { border: '#96CEB4', background: '#F0F9F4' },
  { border: '#FFEAA7', background: '#FFFCF0' },
  { border: '#DDA0DD', background: '#F5F0F5' },
  { border: '#98D8C8', background: '#F0FAF7' },
  { border: '#F7DC6F', background: '#FEFBF0' },
  { border: '#BB8FCE', background: '#F4F1F7' },
  { border: '#85C1E9', background: '#F0F8FF' }
];

export interface CustomNodeData extends Record<string, unknown> {
  label: string;
  description?: string;
  nodeType: string;
  isAsync?: boolean;
  isStreaming?: boolean;
  icon: string;
  colorIndex?: number;
  onDelete?: (nodeId: string) => void;
  onLabelChange?: (nodeId: string, newLabel: string) => void;
  onToggleProperty?: (nodeId: string, property: 'isAsync' | 'isStreaming') => void;
}

type CustomNodeType = Node<CustomNodeData>;

const CustomNode: React.FC<NodeProps<CustomNodeType>> = ({ id, data, selected }) => {
  const [isEditing, setIsEditing] = useState(false);
  const [labelValue, setLabelValue] = useState(data.label);
  const [fixedWidth, setFixedWidth] = useState<number | null>(null);
  const [fixedHeight, setFixedHeight] = useState<number | null>(null);
  const paperRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    setLabelValue(data.label);
  }, [data.label]);

  const colorIndex = data.colorIndex ?? parseInt(id.replace(/\D/g, '')) % pastelColors.length;
  const colors = pastelColors[colorIndex];

  const handleLabelClick = useCallback((e: React.MouseEvent) => {
    e.stopPropagation();
    if (paperRef.current) {
      setFixedWidth(paperRef.current.offsetWidth);
      setFixedHeight(paperRef.current.offsetHeight);
    }
    setIsEditing(true);
  }, []);

  const handleLabelChange = useCallback((event: React.ChangeEvent<HTMLInputElement>) => {
    setLabelValue(event.target.value);
  }, []);

  const handleLabelBlur = useCallback(() => {
    setIsEditing(false);
    setFixedWidth(null);
    setFixedHeight(null);
    if (data.onLabelChange && labelValue.trim() !== data.label) {
      data.onLabelChange(id, labelValue.trim() || data.label);
    }
  }, [data, id, labelValue]);

  const handleLabelKeyDown = useCallback(
    (event: React.KeyboardEvent) => {
      event.stopPropagation();

      if (event.key === 'Enter') {
        handleLabelBlur();
      } else if (event.key === 'Escape') {
        setLabelValue(data.label);
        setIsEditing(false);
        setFixedWidth(null);
        setFixedHeight(null);
      }
    },
    [data.label, handleLabelBlur]
  );

  const isInputNode = data.nodeType === 'input';

  return (
    <div
      ref={paperRef}
      className={`
        min-w-40 max-w-60 relative overflow-visible transition-all duration-200 ease-in-out
        ${selected ? 'shadow-lg scale-105' : 'shadow-sm'}
        ${isInputNode ? 'border-2 border-dashed border-gray-600 bg-white' : 'border-2 border-solid bg-opacity-90'}
        rounded-lg
      `}
      style={{
        width: fixedWidth ? `${fixedWidth}px` : 'fit-content',
        height: fixedHeight ? `${fixedHeight}px` : 'auto',
        borderColor: isInputNode ? '#666' : colors.border,
        backgroundColor: isInputNode ? '#fff' : colors.background
      }}
    >
      <Handle
        type="target"
        position={Position.Top}
        style={{
          background: 'white',
          border: `2px solid ${isInputNode ? '#666' : colors.border}`,
          width: 12,
          height: 12
        }}
      />

      <div
        className={`
        p-3 relative
        ${isInputNode ? 'flex flex-col items-center justify-center h-full text-center' : ''}
      `}
      >
        {selected && !isInputNode && (
          <div className="absolute top-0 right-0 flex gap-px">
            <button
              onClick={() => data.onToggleProperty?.(id, 'isAsync')}
              className="px-1.5 py-0.5 text-[10px] font-semibold transition-opacity rounded-bl"
              style={{
                color: data.isAsync ? 'white' : colors.border,
                backgroundColor: data.isAsync ? colors.border : `${colors.border}22`,
                opacity: data.isAsync ? 1 : 0.6
              }}
              title={data.isAsync ? 'Click to make synchronous' : 'Click to make async'}
            >
              async
            </button>
            <button
              onClick={() => data.onToggleProperty?.(id, 'isStreaming')}
              className="px-1.5 py-0.5 text-[10px] font-semibold transition-opacity rounded-tr-lg"
              style={{
                color: data.isStreaming ? 'white' : colors.border,
                backgroundColor: data.isStreaming ? colors.border : `${colors.border}22`,
                opacity: data.isStreaming ? 1 : 0.6
              }}
              title={data.isStreaming ? 'Click to make regular action' : 'Click to make streaming'}
            >
              stream
            </button>
          </div>
        )}

        {isEditing ? (
          <input
            value={labelValue}
            onChange={handleLabelChange}
            onBlur={handleLabelBlur}
            onKeyDown={handleLabelKeyDown}
            onClick={(e) => e.stopPropagation()}
            autoFocus
            className={`
              border-none outline-none bg-transparent text-sm font-bold font-inherit
              w-full box-border p-0 m-0 leading-normal block
              ${isInputNode ? 'text-center text-gray-600' : 'text-left'}
            `}
            style={{
              color: isInputNode ? '#666' : colors.border,
              marginBottom: data.description ? '8px' : 0,
              paddingRight: selected ? '24px' : 0
            }}
          />
        ) : (
          <div
            onClick={handleLabelClick}
            className={`
              font-bold cursor-pointer hover:opacity-80 break-words min-h-5 min-w-16
              ${isInputNode ? 'text-center text-gray-600' : 'text-left'}
              ${data.description ? 'mb-2' : ''}
            `}
            style={{
              color: isInputNode ? '#666' : colors.border,
              paddingRight: selected ? '12px' : 0
            }}
          >
            {labelValue || <span className="opacity-40 italic font-normal">click to name</span>}
          </div>
        )}

        {data.description && (
          <div
            className={`
              text-xs opacity-80 block break-words
              ${isInputNode ? 'text-center text-gray-600' : 'text-left'}
            `}
            style={{ color: isInputNode ? '#666' : colors.border }}
          >
            {data.description}
          </div>
        )}
      </div>

      <Handle
        type="source"
        position={Position.Bottom}
        style={{
          background: 'white',
          border: `2px solid ${isInputNode ? '#666' : colors.border}`,
          width: 12,
          height: 12
        }}
      />
    </div>
  );
};

export default memo(CustomNode);
