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

import { BaseEdge, EdgeProps } from '@xyflow/react';
import { CANVAS, ARC_LEFT_UP, ARC_RIGHT_UP, ARROW_DOWN } from '../../../../utils/flowLayout';
import { BurrRouterStartEdge, InsertLocation } from '../../../../utils/builderTypes';
import { InlineAddButton } from './InlineAddButton';

export const RouterStartEdgeComponent = ({
  sourceX,
  targetX,
  targetY,
  data
}: EdgeProps & BurrRouterStartEdge) => {
  const vLine = CANVAS.VSPACE - CANVAS.STEP_LINE_GAP + 30;
  const dist = Math.abs(targetX - sourceX);

  let path = `M ${targetX} ${targetY - CANVAS.STEP_LINE_GAP}`;
  if (!data.isBranchEmpty) path += ` ${ARROW_DOWN}`;
  path += ` v -${vLine}`;

  if (dist >= CANVAS.ARC) {
    path += sourceX > targetX ? ' a12,12 0 0,1 12,-12' : ' a-12,-12 0 0,0 -12,-12';
    if (data.drawHorizontalLine) {
      const hLen = (dist + 3 - 2 * CANVAS.ARC) * (sourceX > targetX ? 1 : -1);
      path += ` h ${hLen}`;
      path += sourceX > targetX ? ` ${ARC_LEFT_UP}` : ` ${ARC_RIGHT_UP}`;
    }
    if (data.drawStartingVerticalLine) {
      const finalV = CANVAS.VSPACE / 2 - 2 * CANVAS.STEP_LINE_GAP;
      path += ` v -${finalV}`;
    }
  } else {
    path += ` v -${CANVAS.ARC + CANVAS.STEP_LINE_GAP}`;
  }

  const labelWidth = CANVAS.STEP_WIDTH - 10;
  const labelX = targetX - labelWidth / 2;
  const labelY = targetY - vLine / 2 - CANVAS.ADD_BUTTON_SIZE - 30;

  return (
    <>
      <BaseEdge path={path} style={{ strokeWidth: `${CANVAS.LINE_WIDTH}px` }} />
      {!data.isBranchEmpty && (
        <foreignObject
          x={targetX - CANVAS.ADD_BUTTON_SIZE / 2}
          y={targetY - vLine / 2}
          width={CANVAS.ADD_BUTTON_SIZE}
          height={CANVAS.ADD_BUTTON_SIZE}
          className="overflow-visible"
        >
          <InlineAddButton
            context={{
              location: InsertLocation.INSIDE_BRANCH,
              routerStepId: data.parentStepId,
              branchIndex: data.branchIndex
            }}
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            onInsert={(data as any).onInsert || (() => {})}
          />
        </foreignObject>
      )}
      <foreignObject
        width={labelWidth}
        height={42}
        x={labelX}
        y={labelY}
        className="flex items-center"
      >
        <div className="text-center text-xs font-medium text-gray-500 bg-white px-2 py-1 rounded border border-gray-200 truncate">
          {data.label}
        </div>
      </foreignObject>
    </>
  );
};
