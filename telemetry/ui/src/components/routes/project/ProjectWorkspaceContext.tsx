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

import { createContext, useContext, useState, useCallback, ReactNode } from 'react';

export type TabType = 'file' | 'tracking';

export type Tab = {
  id: string;
  type: TabType;
  label: string;
  filePath?: string;
  appId?: string;
  partitionKey?: string;
};

export type ActivityPanel = 'files' | 'tracking' | 'search';

type ProjectWorkspaceState = {
  projectId: string;
  workspacePath: string | null;
  setWorkspacePath: (p: string | null) => void;
  tabs: Tab[];
  activeTabId: string | null;
  openTab: (tab: Tab) => void;
  closeTab: (id: string) => void;
  setActiveTab: (id: string) => void;
  activePanel: ActivityPanel;
  setActivePanel: (p: ActivityPanel) => void;
  terminalVisible: boolean;
  setTerminalVisible: (v: boolean) => void;
  sidePanelOpen: boolean;
  setSidePanelOpen: (v: boolean) => void;
};

const ProjectWorkspaceCtx = createContext<ProjectWorkspaceState>(null!);

export const useProjectWorkspace = () => useContext(ProjectWorkspaceCtx);

export const ProjectWorkspaceProvider = (props: {
  projectId: string;
  initialWorkspacePath: string | null;
  initialPartitionKey?: string;
  initialAppId?: string;
  children: ReactNode;
}) => {
  const [workspacePath, setWorkspacePath] = useState<string | null>(props.initialWorkspacePath);
  const [tabs, setTabs] = useState<Tab[]>(() => {
    if (props.initialAppId && props.initialPartitionKey) {
      return [
        {
          id: `tracking:${props.initialAppId}`,
          type: 'tracking' as TabType,
          label: props.initialAppId,
          appId: props.initialAppId,
          partitionKey: props.initialPartitionKey
        }
      ];
    }
    return [];
  });
  const [activeTabId, setActiveTabId] = useState<string | null>(
    props.initialAppId ? `tracking:${props.initialAppId}` : null
  );
  const [activePanel, setActivePanel] = useState<ActivityPanel>(
    props.initialAppId ? 'tracking' : 'files'
  );
  const [terminalVisible, setTerminalVisible] = useState(false);
  const [sidePanelOpen, setSidePanelOpen] = useState(true);

  const openTab = useCallback(
    (tab: Tab) => {
      setTabs((prev) => {
        const existing = prev.find((t) => t.id === tab.id);
        if (existing) return prev;
        return [...prev, tab];
      });
      setActiveTabId(tab.id);
    },
    []
  );

  const closeTab = useCallback(
    (id: string) => {
      setTabs((prev) => {
        const filtered = prev.filter((t) => t.id !== id);
        if (activeTabId === id) {
          setActiveTabId(filtered.length > 0 ? filtered[filtered.length - 1].id : null);
        }
        return filtered;
      });
    },
    [activeTabId]
  );

  return (
    <ProjectWorkspaceCtx.Provider
      value={{
        projectId: props.projectId,
        workspacePath,
        setWorkspacePath,
        tabs,
        activeTabId,
        openTab,
        closeTab,
        setActiveTab: setActiveTabId,
        activePanel,
        setActivePanel,
        terminalVisible,
        setTerminalVisible,
        sidePanelOpen,
        setSidePanelOpen
      }}
    >
      {props.children}
    </ProjectWorkspaceCtx.Provider>
  );
};
