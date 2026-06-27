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
import { PlusIcon } from '@heroicons/react/24/outline';
import { InsertContext } from '../../../../utils/builderTypes';
import { NodeType } from '../../../../utils/codeGenerator';
import { NodeTypePicker } from '../NodeTypePicker';

export const InlineAddButton = React.memo(
  (props: { context: InsertContext; onInsert: (nodeType: NodeType, ctx: InsertContext) => void }) => {
    const [pickerOpen, setPickerOpen] = useState(false);
    const btnRef = useRef<HTMLButtonElement>(null);

    return (
      <div
        className="relative flex items-center justify-center"
        style={{ width: 20, height: 20, pointerEvents: 'all' }}
      >
        <button
          ref={btnRef}
          onClick={(e) => {
            e.stopPropagation();
            e.preventDefault();
            setPickerOpen(!pickerOpen);
          }}
          onMouseDown={(e) => e.stopPropagation()}
          style={{ pointerEvents: 'all' }}
          className={`w-[20px] h-[20px] rounded-md border bg-white flex items-center justify-center cursor-pointer transition-all z-10 ${
            pickerOpen
              ? 'border-blue-500 bg-blue-50 shadow-md'
              : 'border-gray-300 hover:border-blue-400 hover:shadow-sm hover:bg-blue-50'
          }`}
        >
          {!pickerOpen && <PlusIcon className="w-3 h-3 stroke-[3px] text-gray-500" />}
        </button>
        {pickerOpen && (
          <NodeTypePicker
            anchorRef={btnRef as React.RefObject<HTMLElement>}
            onSelect={(nodeType) => props.onInsert(nodeType, props.context)}
            onClose={() => setPickerOpen(false)}
          />
        )}
      </div>
    );
  }
);

InlineAddButton.displayName = 'InlineAddButton';
