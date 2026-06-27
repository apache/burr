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
import { useNavigate } from 'react-router-dom';
import { FolderIcon, XMarkIcon } from '@heroicons/react/24/outline';
import { workspaceApi } from '../../../api/workspaceApi';

const STORAGE_KEY = 'burr:recent_workspaces';

function getRecentWorkspaces(): string[] {
  try {
    return JSON.parse(localStorage.getItem(STORAGE_KEY) || '[]');
  } catch {
    return [];
  }
}

function addRecentWorkspace(path: string) {
  const recent = getRecentWorkspaces().filter((p) => p !== path);
  recent.unshift(path);
  localStorage.setItem(STORAGE_KEY, JSON.stringify(recent.slice(0, 10)));
}

function removeRecentWorkspace(path: string) {
  const recent = getRecentWorkspaces().filter((p) => p !== path);
  localStorage.setItem(STORAGE_KEY, JSON.stringify(recent));
}

function encodePath(path: string): string {
  return btoa(path).replace(/\+/g, '-').replace(/\//g, '_').replace(/=/g, '');
}

export const WorkspaceSelector = () => {
  const [path, setPath] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const navigate = useNavigate();
  const recentWorkspaces = getRecentWorkspaces();

  const openWorkspace = async (workspacePath: string) => {
    setError('');
    setLoading(true);
    try {
      const info = await workspaceApi.openWorkspace(workspacePath);
      addRecentWorkspace(info.path);
      navigate(`/workspace/${encodePath(info.path)}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to open workspace');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="max-w-2xl mx-auto py-8">
      <h1 className="text-2xl font-bold text-gray-900 mb-6">Open Workspace</h1>

      <div className="flex gap-3 mb-4">
        <input
          type="text"
          value={path}
          onChange={(e) => setPath(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && path && openWorkspace(path)}
          placeholder="/absolute/path/to/project"
          className="flex-1 rounded-md border border-gray-300 px-4 py-2 text-sm focus:border-blue-500 focus:ring-1 focus:ring-blue-500 outline-none"
        />
        <button
          onClick={() => openWorkspace(path)}
          disabled={!path || loading}
          className="rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {loading ? 'Opening...' : 'Open'}
        </button>
      </div>

      {error && <p className="text-sm text-red-600 mb-4">{error}</p>}

      {recentWorkspaces.length > 0 && (
        <div className="mt-8">
          <h2 className="text-sm font-semibold text-gray-500 uppercase tracking-wide mb-3">
            Recent Workspaces
          </h2>
          <ul className="divide-y divide-gray-100 rounded-md border border-gray-200">
            {recentWorkspaces.map((ws) => (
              <li key={ws} className="flex items-center justify-between px-4 py-3 hover:bg-gray-50">
                <button
                  onClick={() => openWorkspace(ws)}
                  className="flex items-center gap-3 text-left flex-1 min-w-0"
                >
                  <FolderIcon className="h-5 w-5 text-gray-400 shrink-0" />
                  <span className="text-sm text-gray-700 truncate">{ws}</span>
                </button>
                <button
                  onClick={(e) => {
                    e.stopPropagation();
                    removeRecentWorkspace(ws);
                    // Force re-render by navigating to same page
                    navigate('/workspace', { replace: true });
                  }}
                  className="ml-2 text-gray-400 hover:text-gray-600"
                >
                  <XMarkIcon className="h-4 w-4" />
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
};
