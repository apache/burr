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

import { useState } from 'react';
import { FolderIcon } from '@heroicons/react/24/outline';
import { workspaceApi } from '../../../api/workspaceApi';
import { useProjectWorkspace } from './ProjectWorkspaceContext';

export const LinkWorkspacePrompt = () => {
  const { projectId, setWorkspacePath } = useProjectWorkspace();
  const [path, setPath] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  const handleLink = async () => {
    if (!path) return;
    setError('');
    setLoading(true);
    try {
      const info = await workspaceApi.setWorkspaceLink(projectId, path);
      if (info.workspace_path) {
        setWorkspacePath(info.workspace_path);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to link workspace');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex items-center justify-center h-full">
      <div className="max-w-md w-full p-8">
        <div className="flex items-center gap-3 mb-4">
          <FolderIcon className="h-8 w-8 text-gray-400" />
          <div>
            <h2 className="text-lg font-semibold text-gray-900">Link a workspace</h2>
            <p className="text-sm text-gray-500">
              Connect a code directory to browse files and run scripts.
            </p>
          </div>
        </div>
        <div className="flex gap-2 mt-4">
          <input
            type="text"
            value={path}
            onChange={(e) => setPath(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && handleLink()}
            placeholder="/absolute/path/to/project"
            className="flex-1 rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:ring-1 focus:ring-blue-500 outline-none"
          />
          <button
            onClick={handleLink}
            disabled={!path || loading}
            className="rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
          >
            {loading ? '...' : 'Link'}
          </button>
        </div>
        {error && <p className="text-sm text-red-600 mt-2">{error}</p>}
      </div>
    </div>
  );
};
