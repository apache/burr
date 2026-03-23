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
import { CANVAS, ARC_RIGHT_DOWN, ARC_RIGHT, ARROW_DOWN } from '../../../../utils/flowLayout';
import { BurrLoopStartEdge, InsertLocation } from '../../../../utils/builderTypes';
import { InlineAddButton } from './InlineAddButton';

export const LoopStartEdgeComponent = ({
  sourceX,
  sourceY,
  targetX,
  data,
  id
}: EdgeProps & BurrLoopStartEdge) => {
  const startY = sourceY + CANVAS.STEP_LINE_GAP;
  const vHalf = (CANVAS.VSPACE - 2 * CANVAS.STEP_LINE_GAP) / 2;
  const hLength = Math.abs(targetX - sourceX) - 2 * CANVAS.ARC;

  const path = `M ${sourceX} ${startY} v${vHalf} ${ARC_RIGHT_DOWN} h${hLength} ${ARC_RIGHT} v${CANVAS.VSPACE} ${!data.isLoopEmpty ? ARROW_DOWN : ''}`;

  const buttonX = sourceX - CANVAS.ADD_BUTTON_SIZE / 2 + hLength + CANVAS.ARC * 2;
  const buttonY = startY + vHalf + CANVAS.ARC;

  return (
    <>
      <BaseEdge path={path} style={{ strokeWidth: `${CANVAS.LINE_WIDTH}px` }} />
      {!data.isLoopEmpty && (
        <foreignObject
          x={buttonX}
          y={buttonY}
          width={CANVAS.ADD_BUTTON_SIZE}
          height={CANVAS.ADD_BUTTON_SIZE}
          className="overflow-visible cursor-default"
        >
          <InlineAddButton
            context={{ location: InsertLocation.INSIDE_LOOP, loopStepId: data.parentStepId }}
            onInsert={(data as any).onInsert || (() => {})}
          />
        </foreignObject>
      )}
    </>
  );
};
