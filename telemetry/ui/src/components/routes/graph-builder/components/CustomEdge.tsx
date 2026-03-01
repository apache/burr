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

import React, { useState, useCallback } from 'react';
import {
  BaseEdge,
  EdgeLabelRenderer,
  EdgeProps,
  getBezierPath,
  MarkerType,
  Edge
} from '@xyflow/react';

export interface CustomEdgeData extends Record<string, unknown> {
  condition?: string;
  isConditional?: boolean;
  label?: string;
  onLabelChange?: (edgeId: string, newLabel: string) => void;
}

type CustomEdgeType = Edge<CustomEdgeData>;

const CustomEdge: React.FC<EdgeProps<CustomEdgeType>> = ({
  id,
  sourceX,
  sourceY,
  targetX,
  targetY,
  sourcePosition,
  targetPosition,
  style = {},
  data,
  markerEnd,
  selected
}) => {
  const [isEditing, setIsEditing] = useState(false);

  const isConditional = data?.isConditional || (data?.condition && data.condition !== 'default');
  const displayLabel = isConditional ? data?.label || 'condition' : '';
  const [labelValue, setLabelValue] = useState(displayLabel);

  React.useEffect(() => {
    const newDisplayLabel = isConditional ? data?.label || 'condition' : '';
    setLabelValue(newDisplayLabel);
  }, [data?.label, data?.condition, isConditional]);

  const [edgePath, labelX, labelY] = getBezierPath({
    sourceX,
    sourceY,
    sourcePosition,
    targetX,
    targetY,
    targetPosition
  });

  const edgeStyle: React.CSSProperties = {
    strokeWidth: selected ? 4 : 2,
    stroke:
      (style as React.CSSProperties)?.stroke ||
      (data?.condition === 'default' ? '#94a3b8' : '#429dbce6'),
    ...(style as React.CSSProperties)
  };

  if (isConditional) {
    edgeStyle.strokeDasharray = '8,4';
    edgeStyle.animation = 'dash 2s linear infinite';
  }

  const handleLabelClick = useCallback((e: React.MouseEvent) => {
    e.stopPropagation();
    setIsEditing(true);
  }, []);

  const handleLabelChange = useCallback((event: React.ChangeEvent<HTMLInputElement>) => {
    setLabelValue(event.target.value);
  }, []);

  const handleLabelBlur = useCallback(() => {
    setIsEditing(false);
    if (data?.onLabelChange) {
      data.onLabelChange(id, labelValue);
    }
  }, [data, id, labelValue]);

  const handleLabelKeyDown = useCallback(
    (event: React.KeyboardEvent) => {
      event.stopPropagation();

      if (event.key === 'Enter') {
        handleLabelBlur();
      } else if (event.key === 'Escape') {
        setLabelValue(data?.label || data?.condition || '');
        setIsEditing(false);
      }
    },
    [data?.label, data?.condition, handleLabelBlur]
  );

  return (
    <>
      <style>
        {`
          @keyframes dash {
            to {
              stroke-dashoffset: -12;
            }
          }
        `}
      </style>

      <BaseEdge path={edgePath} markerEnd={markerEnd || MarkerType.ArrowClosed} style={edgeStyle} />
      <EdgeLabelRenderer>
        {isConditional && (
          <div
            className="absolute text-xs pointer-events-auto"
            style={{
              transform: `translate(-50%, -50%) translate(${labelX}px,${labelY}px)`
            }}
          >
            {isEditing ? (
              <input
                value={labelValue}
                onChange={handleLabelChange}
                onBlur={handleLabelBlur}
                onKeyDown={handleLabelKeyDown}
                onClick={(e) => e.stopPropagation()}
                autoFocus
                className="border border-gray-300 rounded-xl px-2 py-1 text-xs bg-white min-w-16 text-center focus:outline-none focus:ring-2 focus:ring-blue-500"
              />
            ) : (
              <button
                onClick={handleLabelClick}
                className="bg-white border border-gray-300 rounded-xl px-2 py-1 text-xs cursor-pointer hover:bg-gray-50 transition-colors min-h-5 flex items-center"
              >
                {data?.label ?? data?.condition ?? ''}
              </button>
            )}
          </div>
        )}
      </EdgeLabelRenderer>
    </>
  );
};

export default CustomEdge;
