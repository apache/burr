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
import {
  CANVAS,
  ARC_RIGHT_DOWN,
  ARC_LEFT_DOWN,
  ARC_RIGHT,
  ARC_LEFT,
  ARROW_DOWN
} from '../../../../utils/flowLayout';
import { BurrRouterEndEdge, InsertLocation } from '../../../../utils/builderTypes';
import { InlineAddButton } from './InlineAddButton';

export const RouterEndEdgeComponent = ({
  sourceX,
  targetX,
  targetY,
  sourceY,
  data,
  id
}: EdgeProps & BurrRouterEndEdge) => {
  const vLine = CANVAS.VSPACE - 2 * CANVAS.STEP_LINE_GAP;
  const hLength =
    (Math.abs(targetX - sourceX) - 2 * CANVAS.ARC) * (targetX > sourceX ? 1 : -1);
  const dist = Math.abs(targetX - sourceX);

  let path = `M ${sourceX - 0.5} ${sourceY - CANVAS.STEP_LINE_GAP}`;
  path += ` v ${data.verticalSpaceBetweenLastNodeInBranchAndEndLine}`;

  if (dist >= CANVAS.ARC) {
    path += targetX > sourceX ? ` ${ARC_RIGHT_DOWN}` : ` ${ARC_LEFT_DOWN}`;
  } else {
    path += ` v ${CANVAS.ARC + CANVAS.STEP_LINE_GAP + 2}`;
  }

  if (data.drawHorizontalLine) {
    path += ` h ${hLength}`;
    path += targetX > sourceX ? ` ${ARC_RIGHT}` : ` ${ARC_LEFT}`;
  }

  if (data.drawEndingVerticalLine) {
    path += ` v${vLine}`;
    if (!data.isNextStepEmpty) path += ` ${ARROW_DOWN}`;
  }

  return (
    <>
      <BaseEdge path={path} style={{ strokeWidth: `${CANVAS.LINE_WIDTH}px` }} />
      {data.drawEndingVerticalLine && data.routerStepId && (
        <foreignObject
          x={targetX - CANVAS.ADD_BUTTON_SIZE / 2 - CANVAS.LINE_WIDTH / 2}
          y={targetY - vLine}
          width={CANVAS.ADD_BUTTON_SIZE}
          height={CANVAS.ADD_BUTTON_SIZE}
          className="overflow-visible"
        >
          <InlineAddButton
            context={{ location: InsertLocation.AFTER, parentStepId: data.routerStepId }}
            onInsert={(data as any).onInsert || (() => {})}
          />
        </foreignObject>
      )}
    </>
  );
};
