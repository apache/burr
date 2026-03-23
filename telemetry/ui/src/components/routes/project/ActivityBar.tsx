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

import {
  DocumentTextIcon,
  Square2StackIcon,
  MagnifyingGlassIcon,
  CommandLineIcon
} from '@heroicons/react/24/outline';
import { classNames } from '../../../utils/tailwind';
import { ActivityPanel, useProjectWorkspace } from './ProjectWorkspaceContext';

const items: { id: ActivityPanel | 'terminal'; icon: React.ComponentType<any>; label: string }[] = [
  { id: 'files', icon: DocumentTextIcon, label: 'Files' },
  { id: 'tracking', icon: Square2StackIcon, label: 'Tracking' },
  { id: 'search', icon: MagnifyingGlassIcon, label: 'Search' },
  { id: 'terminal', icon: CommandLineIcon, label: 'Terminal' }
];

export const ActivityBar = () => {
  const { activePanel, setActivePanel, sidePanelOpen, setSidePanelOpen, terminalVisible, setTerminalVisible } =
    useProjectWorkspace();

  return (
    <div className="w-12 shrink-0 bg-gray-50 border-r border-gray-200 flex flex-col items-center py-2 gap-1">
      {items.map((item) => {
        const isTerminal = item.id === 'terminal';
        const isActive = isTerminal ? terminalVisible : activePanel === item.id && sidePanelOpen;
        return (
          <button
            key={item.id}
            onClick={() => {
              if (isTerminal) {
                setTerminalVisible(!terminalVisible);
              } else {
                if (activePanel === item.id && sidePanelOpen) {
                  setSidePanelOpen(false);
                } else {
                  setActivePanel(item.id as ActivityPanel);
                  setSidePanelOpen(true);
                }
              }
            }}
            className={classNames(
              'w-10 h-10 flex items-center justify-center rounded-md transition-colors',
              isActive
                ? 'text-gray-900 bg-white shadow-sm border border-gray-200'
                : 'text-gray-400 hover:text-gray-600 hover:bg-gray-100'
            )}
            title={item.label}
          >
            <item.icon className="h-5 w-5" />
          </button>
        );
      })}
    </div>
  );
};
