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
import { CANVAS, ARC_LEFT_DOWN, ARC_RIGHT_UP, ARROW_DOWN } from '../../../../utils/flowLayout';
import { BurrLoopReturnEdge, InsertLocation } from '../../../../utils/builderTypes';
import { InlineAddButton } from './InlineAddButton';

export const LoopReturnEdgeComponent = ({
  sourceX,
  sourceY,
  targetX,
  data,
  id
}: EdgeProps & BurrLoopReturnEdge) => {
  const hLength = Math.abs(sourceX - targetX) - 2 * CANVAS.ARC;
  const vReturn = data.verticalSpaceBetweenReturnNodeStartAndEnd;
  const endLineLength = CANVAS.VSPACE - 2 * CANVAS.STEP_LINE_GAP + 8;

  const path = `
    M ${sourceX - 0.5} ${sourceY - CANVAS.STEP_LINE_GAP}
    v 1
    ${ARC_LEFT_DOWN} h -${hLength}
    ${ARC_RIGHT_UP} v -${vReturn}
    a${CANVAS.ARC},${CANVAS.ARC} 0 0,1 ${CANVAS.ARC},-${CANVAS.ARC}
    h ${hLength / 2 - 2 * CANVAS.ARC}
    m-5 -6 l6 6 m-6 0 m6 0 l-6 6 m3 -6
    M ${sourceX - CANVAS.ARC - hLength / 2} ${sourceY + CANVAS.STEP_LINE_GAP + CANVAS.ARC / 2}
    v${endLineLength} ${data.drawArrowHeadAfterEnd ? ARROW_DOWN : ''}
  `;

  const buttonX = sourceX - hLength / 2 - CANVAS.ARC - CANVAS.ADD_BUTTON_SIZE / 2;
  const buttonY = sourceY + endLineLength / 2;

  return (
    <>
      <BaseEdge path={path} style={{ strokeWidth: `${CANVAS.LINE_WIDTH}px` }} />
      <foreignObject
        x={buttonX}
        y={buttonY}
        width={CANVAS.ADD_BUTTON_SIZE}
        height={CANVAS.ADD_BUTTON_SIZE}
        className="overflow-visible"
      >
        <InlineAddButton
          context={{ location: InsertLocation.AFTER, parentStepId: data.parentStepId }}
          onInsert={(data as any).onInsert || (() => {})}
        />
      </foreignObject>
    </>
  );
};
