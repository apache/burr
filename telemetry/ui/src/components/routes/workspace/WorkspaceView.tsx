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
import { useParams } from 'react-router-dom';
import { FileExplorer } from './FileExplorer';
import { CodeViewer } from './CodeViewer';
import { RunTerminal } from './RunTerminal';
import { FileEntry, ProcessInfo, workspaceApi } from '../../../api/workspaceApi';

function decodePath(encoded: string): string {
  const base64 = encoded.replace(/-/g, '+').replace(/_/g, '/');
  // Add padding if needed
  const padded = base64 + '='.repeat((4 - (base64.length % 4)) % 4);
  return atob(padded);
}

export const WorkspaceView = () => {
  const { encodedPath } = useParams<{ encodedPath: string }>();
  const workspace = decodePath(encodedPath || '');

  const [rootEntries, setRootEntries] = useState<FileEntry[]>([]);
  const [selectedFile, setSelectedFile] = useState<string | null>(null);
  const [activeProcess, setActiveProcess] = useState<ProcessInfo | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!workspace) return;
    setLoading(true);
    workspaceApi
      .getFileTree(workspace)
      .then(setRootEntries)
      .finally(() => setLoading(false));
  }, [workspace]);

  const handleRunScript = async (relativePath: string) => {
    try {
      const proc = await workspaceApi.runScript(workspace, relativePath);
      setActiveProcess(proc);
    } catch (err) {
      alert(err instanceof Error ? err.message : 'Failed to run script');
    }
  };

  if (!workspace) {
    return <div className="text-red-500 p-4">Invalid workspace path</div>;
  }

  if (loading) {
    return <div className="flex items-center justify-center h-full text-gray-400">Loading...</div>;
  }

  return (
    <div className="flex h-full" style={{ height: 'calc(100vh - 120px)' }}>
      {/* File Explorer sidebar */}
      <div className="w-64 shrink-0 border-r border-gray-200 overflow-hidden">
        <div className="px-3 py-2 border-b border-gray-200">
          <h2 className="text-sm font-semibold text-gray-700 truncate" title={workspace}>
            {workspace.split('/').pop()}
          </h2>
        </div>
        <FileExplorer
          workspace={workspace}
          rootEntries={rootEntries}
          onSelectFile={setSelectedFile}
          onRunScript={handleRunScript}
        />
      </div>

      {/* Main content area */}
      <div className="flex-1 flex flex-col min-w-0">
        {/* Code viewer */}
        <div className={`${activeProcess ? 'h-3/5' : 'h-full'} border-b border-gray-200`}>
          {selectedFile ? (
            <CodeViewer workspace={workspace} filePath={selectedFile} />
          ) : (
            <div className="flex items-center justify-center h-full text-gray-400 text-sm">
              Select a file to view
            </div>
          )}
        </div>

        {/* Terminal */}
        {activeProcess && (
          <div className="h-2/5">
            <RunTerminal process={activeProcess} onStopped={() => setActiveProcess(null)} />
          </div>
        )}
      </div>
    </div>
  );
};
