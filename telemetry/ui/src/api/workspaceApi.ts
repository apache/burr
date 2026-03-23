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

import { fetchEventSource } from '@microsoft/fetch-event-source';

const BASE = '/api/v0/workspace';

export interface WorkspaceInfo {
  path: string;
  name: string;
}

export interface FileEntry {
  name: string;
  path: string;
  is_dir: boolean;
  size: number;
  modified: number;
  is_python: boolean;
  has_burr_app: boolean;
}

export interface FileContent {
  path: string;
  content: string;
  language: string;
  size: number;
}

export interface ProcessInfo {
  pid: number;
  script_path: string;
  started_at: number;
  status: string;
  exit_code: number | null;
}

export interface ProcessOutputEvent {
  type: 'stdout' | 'stderr' | 'exit';
  data: string;
}

export interface WorkspaceLinkInfo {
  project_id: string;
  workspace_path: string | null;
}

export interface BuilderProjectSummary {
  id: string;
  name: string;
  updated_at: number;
}

export interface BuilderProjectFull {
  id: string;
  name: string;
  graph_json: string;
  updated_at: number;
}

async function apiPost<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body)
  });
  if (!res.ok) {
    const detail = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(detail.detail || res.statusText);
  }
  return res.json();
}

async function apiGet<T>(path: string, params?: Record<string, string>): Promise<T> {
  const url = new URL(`${BASE}${path}`, window.location.origin);
  if (params) {
    Object.entries(params).forEach(([k, v]) => url.searchParams.set(k, v));
  }
  const res = await fetch(url.toString());
  if (!res.ok) {
    const detail = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(detail.detail || res.statusText);
  }
  return res.json();
}

export const workspaceApi = {
  getWorkspaceLink(projectId: string): Promise<WorkspaceLinkInfo> {
    return apiGet('/link', { project_id: projectId });
  },

  setWorkspaceLink(projectId: string, workspacePath: string): Promise<WorkspaceLinkInfo> {
    return apiPost('/link', { project_id: projectId, workspace_path: workspacePath });
  },

  removeWorkspaceLink(projectId: string): Promise<void> {
    const url = new URL(`${BASE}/link`, window.location.origin);
    url.searchParams.set('project_id', projectId);
    return fetch(url.toString(), { method: 'DELETE' }).then(() => undefined);
  },

  openWorkspace(path: string): Promise<WorkspaceInfo> {
    return apiPost('/open', { path });
  },

  getFileTree(workspace: string, relativePath = ''): Promise<FileEntry[]> {
    return apiGet('/tree', { workspace, relative_path: relativePath });
  },

  getFileContent(workspace: string, relativePath: string): Promise<FileContent> {
    return apiGet('/file', { workspace, relative_path: relativePath });
  },

  runScript(workspace: string, script: string): Promise<ProcessInfo> {
    return apiPost('/run', { workspace, script });
  },

  stopProcess(pid: number): Promise<ProcessInfo> {
    return apiPost(`/run/${pid}/stop`, {});
  },

  getProcesses(workspace: string): Promise<ProcessInfo[]> {
    return apiGet('/processes', { workspace });
  },

  scanBurrApps(workspace: string): Promise<FileEntry[]> {
    return apiGet('/scan', { workspace });
  },

  listBuilderProjects(): Promise<BuilderProjectSummary[]> {
    return apiGet('/builder/projects');
  },

  saveBuilderProject(name: string, graphJson: string): Promise<BuilderProjectFull> {
    return apiPost('/builder/projects', { name, graph_json: graphJson });
  },

  getBuilderProject(id: string): Promise<BuilderProjectFull> {
    return apiGet(`/builder/projects/${id}`);
  },

  deleteBuilderProject(id: string): Promise<void> {
    return fetch(`${BASE}/builder/projects/${id}`, { method: 'DELETE' }).then(() => undefined);
  },

  streamProcessOutput(
    pid: number,
    onEvent: (event: ProcessOutputEvent) => void,
    onError: (err: Error) => void
  ): AbortController {
    const ctrl = new AbortController();
    fetchEventSource(`${BASE}/run/${pid}/output`, {
      signal: ctrl.signal,
      onmessage(ev) {
        try {
          const parsed: ProcessOutputEvent = JSON.parse(ev.data);
          onEvent(parsed);
        } catch {
          // ignore parse errors
        }
      },
      onerror(err) {
        onError(err instanceof Error ? err : new Error(String(err)));
      },
      openWhenHidden: true
    });
    return ctrl;
  }
};
