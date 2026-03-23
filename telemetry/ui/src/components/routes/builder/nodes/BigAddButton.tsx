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

import React, { useRef, useState } from 'react';
import { Handle, Position } from '@xyflow/react';
import { PlusIcon } from '@heroicons/react/24/outline';
import { CANVAS } from '../../../../utils/flowLayout';
import { BurrBigAddButtonNode, InsertContext } from '../../../../utils/builderTypes';
import { NodeType } from '../../../../utils/codeGenerator';
import { NodeTypePicker } from '../NodeTypePicker';

const HANDLE_STYLE = { opacity: 0, cursor: 'default' };

const BigAddButtonComponent = React.memo(
  ({ data, id }: { data: BurrBigAddButtonNode['data'] & { onInsert?: (nodeType: NodeType, ctx: InsertContext) => void }; id: string }) => {
    const [pickerOpen, setPickerOpen] = useState(false);
    const btnRef = useRef<HTMLButtonElement>(null);

    return (
      <>
        <div
          style={{ width: CANVAS.STEP_WIDTH, height: CANVAS.STEP_HEIGHT }}
          className="flex items-center justify-center"
        >
          <div className="relative">
            <button
              ref={btnRef}
              onClick={(e) => {
                e.stopPropagation();
                setPickerOpen(!pickerOpen);
              }}
              onMouseDown={(e) => e.stopPropagation()}
              style={{ width: CANVAS.BIG_ADD_BUTTON_SIZE, height: CANVAS.BIG_ADD_BUTTON_SIZE }}
              className={`rounded-lg border bg-white flex items-center justify-center cursor-pointer hover:border-blue-400 hover:bg-blue-50 transition-all ${
                pickerOpen ? 'border-blue-500 bg-blue-50 shadow-md' : 'border-gray-300'
              }`}
            >
              <PlusIcon className="w-6 h-6 text-gray-400" />
            </button>
            {pickerOpen && (
              <NodeTypePicker
                anchorRef={btnRef as React.RefObject<HTMLElement>}
                onSelect={(nodeType) => {
                  if (data.onInsert) {
                    data.onInsert(nodeType, data as InsertContext);
                  }
                }}
                onClose={() => setPickerOpen(false)}
              />
            )}
          </div>
        </div>
        <Handle type="target" position={Position.Top} style={HANDLE_STYLE} />
        <Handle type="source" position={Position.Bottom} style={HANDLE_STYLE} />
      </>
    );
  }
);

BigAddButtonComponent.displayName = 'BigAddButtonComponent';
export { BigAddButtonComponent };
