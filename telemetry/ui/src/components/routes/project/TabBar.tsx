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

import { XMarkIcon, DocumentTextIcon, Square2StackIcon } from '@heroicons/react/24/outline';
import { classNames } from '../../../utils/tailwind';
import { useProjectWorkspace } from './ProjectWorkspaceContext';

export const TabBar = () => {
  const { tabs, activeTabId, setActiveTab, closeTab } = useProjectWorkspace();

  if (tabs.length === 0) return null;

  return (
    <div className="flex items-center bg-gray-50 border-b border-gray-200 overflow-x-auto shrink-0">
      {tabs.map((tab) => {
        const isActive = tab.id === activeTabId;
        const Icon = tab.type === 'file' ? DocumentTextIcon : Square2StackIcon;
        return (
          <div
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            onAuxClick={(e) => {
              if (e.button === 1) closeTab(tab.id);
            }}
            className={classNames(
              'flex items-center gap-1.5 px-3 py-1.5 text-xs cursor-pointer border-r border-gray-200 select-none shrink-0',
              isActive
                ? 'bg-white text-gray-900 border-b-2 border-b-blue-500'
                : 'text-gray-500 hover:bg-gray-100'
            )}
          >
            <Icon className="h-3.5 w-3.5 shrink-0" />
            <span className="truncate max-w-[140px]">{tab.label}</span>
            <button
              onClick={(e) => {
                e.stopPropagation();
                closeTab(tab.id);
              }}
              className="ml-1 p-0.5 rounded hover:bg-gray-200"
            >
              <XMarkIcon className="h-3 w-3" />
            </button>
          </div>
        );
      })}
    </div>
  );
};
