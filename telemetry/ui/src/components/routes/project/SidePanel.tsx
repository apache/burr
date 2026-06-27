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

import { useEffect, useState } from 'react';
import { useProjectWorkspace } from './ProjectWorkspaceContext';
import { FileExplorer } from '../workspace/FileExplorer';
import { TrackingSidePanel } from './TrackingSidePanel';
import { FileEntry, workspaceApi } from '../../../api/workspaceApi';
import { MagnifyingGlassIcon } from '@heroicons/react/24/outline';

const FilesSidePanel = () => {
  const { workspacePath, openTab, setTerminalVisible } = useProjectWorkspace();
  const [rootEntries, setRootEntries] = useState<FileEntry[]>([]);

  useEffect(() => {
    if (workspacePath) {
      workspaceApi.getFileTree(workspacePath).then(setRootEntries);
    }
  }, [workspacePath]);

  if (!workspacePath) {
    return <div className="px-3 py-4 text-xs text-gray-400">No workspace linked</div>;
  }

  return (
    <FileExplorer
      workspace={workspacePath}
      rootEntries={rootEntries}
      onSelectFile={(path) => {
        const name = path.split('/').pop() || path;
        openTab({ id: `file:${path}`, type: 'file', label: name, filePath: path });
      }}
      onRunScript={async (path) => {
        try {
          const proc = await workspaceApi.runScript(workspacePath, path);
          setTerminalVisible(true);
          // Store process info in sessionStorage for the terminal to pick up
          sessionStorage.setItem('burr:active_process', JSON.stringify(proc));
          window.dispatchEvent(new Event('burr:process_started'));
        } catch (err) {
          alert(err instanceof Error ? err.message : 'Failed to run script');
        }
      }}
    />
  );
};

const SearchSidePanel = () => {
  const { workspacePath } = useProjectWorkspace();
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<FileEntry[]>([]);
  const { openTab } = useProjectWorkspace();

  const doSearch = async () => {
    if (!workspacePath || !query) return;
    const apps = await workspaceApi.scanBurrApps(workspacePath);
    setResults(apps.filter((f) => f.name.toLowerCase().includes(query.toLowerCase())));
  };

  return (
    <div className="flex flex-col h-full">
      <div className="px-3 py-2 border-b border-gray-200">
        <div className="flex items-center gap-1 bg-gray-100 rounded-md px-2 py-1">
          <MagnifyingGlassIcon className="h-4 w-4 text-gray-400 shrink-0" />
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && doSearch()}
            placeholder="Search files..."
            className="flex-1 bg-transparent text-sm outline-none"
          />
        </div>
      </div>
      <div className="flex-1 overflow-y-auto">
        {results.map((f) => (
          <button
            key={f.path}
            onClick={() => openTab({ id: `file:${f.path}`, type: 'file', label: f.name, filePath: f.path })}
            className="w-full text-left px-3 py-1.5 text-sm text-gray-700 hover:bg-gray-50 truncate"
          >
            {f.path}
          </button>
        ))}
      </div>
    </div>
  );
};

export const SidePanel = () => {
  const { activePanel, sidePanelOpen } = useProjectWorkspace();

  if (!sidePanelOpen) return null;

  return (
    <div className="w-64 shrink-0 border-r border-gray-200 flex flex-col overflow-hidden bg-white">
      {activePanel === 'files' && <FilesSidePanel />}
      {activePanel === 'tracking' && <TrackingSidePanel />}
      {activePanel === 'search' && <SearchSidePanel />}
    </div>
  );
};
