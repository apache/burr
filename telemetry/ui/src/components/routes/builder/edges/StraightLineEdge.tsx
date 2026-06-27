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
import { CANVAS, ARROW_DOWN } from '../../../../utils/flowLayout';
import { BurrStraightLineEdge, InsertLocation } from '../../../../utils/builderTypes';
import { InlineAddButton } from './InlineAddButton';

export const StraightLineEdgeComponent = ({
  sourceX,
  sourceY,
  targetY,
  data
}: EdgeProps & BurrStraightLineEdge) => {
  const lineLength = targetY - sourceY;
  const path = `M ${sourceX} ${sourceY} v${lineLength} ${data.drawArrowHead ? ARROW_DOWN : ''}`;
  const midY = sourceY + lineLength / 2 - CANVAS.ADD_BUTTON_SIZE / 2;

  return (
    <>
      <BaseEdge path={path} style={{ strokeWidth: `${CANVAS.LINE_WIDTH}px` }} />
      {!data.hideAddButton && (
        <foreignObject
          x={sourceX - CANVAS.ADD_BUTTON_SIZE / 2}
          y={midY}
          width={CANVAS.ADD_BUTTON_SIZE}
          height={CANVAS.ADD_BUTTON_SIZE}
          className="overflow-visible"
          style={{ pointerEvents: 'all' }}
        >
          <InlineAddButton
            context={{ location: InsertLocation.AFTER, parentStepId: data.parentStepId }}
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            onInsert={(data as any).onInsert || (() => {})}
          />
        </foreignObject>
      )}
    </>
  );
};
