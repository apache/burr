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
import { useQuery } from '@tanstack/react-query';
import { workspaceApi, ProcessInfo } from '../../../api/workspaceApi';
import { ProjectWorkspaceProvider, useProjectWorkspace } from './ProjectWorkspaceContext';
import { ActivityBar } from './ActivityBar';
import { SidePanel } from './SidePanel';
import { TabBar } from './TabBar';
import { LinkWorkspacePrompt } from './LinkWorkspacePrompt';
import { CodeViewer } from '../workspace/CodeViewer';
import { RunTerminal } from '../workspace/RunTerminal';
import { AppView } from '../app/AppView';
import { Loading } from '../../common/loading';

const EditorContent = () => {
  const { projectId, tabs, activeTabId, workspacePath } = useProjectWorkspace();
  const activeTab = tabs.find((t) => t.id === activeTabId);

  if (!activeTab) {
    if (!workspacePath) {
      return <LinkWorkspacePrompt />;
    }
    return (
      <div className="flex items-center justify-center h-full text-gray-400 text-sm">
        Open a file or select a run from the sidebar
      </div>
    );
  }

  if (activeTab.type === 'file' && activeTab.filePath && workspacePath) {
    return <CodeViewer workspace={workspacePath} filePath={activeTab.filePath} />;
  }

  if (activeTab.type === 'tracking' && activeTab.appId) {
    return (
      <div className="h-full overflow-auto">
        <AppView
          projectId={projectId}
          appId={activeTab.appId}
          partitionKey={activeTab.partitionKey || null}
          orientation="stacked_vertical"
          defaultAutoRefresh={false}
          enableFullScreenStepView={true}
          enableMinimizedStepView={true}
          allowAnnotations={true}
        />
      </div>
    );
  }

  return null;
};

const TerminalPanel = () => {
  const { terminalVisible, setTerminalVisible } = useProjectWorkspace();
  const [activeProcess, setActiveProcess] = useState<ProcessInfo | null>(null);

  useEffect(() => {
    const handler = () => {
      const stored = sessionStorage.getItem('burr:active_process');
      if (stored) {
        setActiveProcess(JSON.parse(stored));
        sessionStorage.removeItem('burr:active_process');
      }
    };
    window.addEventListener('burr:process_started', handler);
    return () => window.removeEventListener('burr:process_started', handler);
  }, []);

  if (!terminalVisible || !activeProcess) return null;

  return (
    <div className="h-64 border-t border-gray-200 shrink-0">
      <RunTerminal
        process={activeProcess}
        onStopped={() => {
          setActiveProcess(null);
          setTerminalVisible(false);
        }}
      />
    </div>
  );
};

const ProjectWorkspaceInner = () => {
  return (
    <div className="flex h-full">
      <ActivityBar />
      <SidePanel />
      <div className="flex-1 flex flex-col min-w-0">
        <TabBar />
        <div className="flex-1 min-h-0 overflow-hidden">
          <EditorContent />
        </div>
        <TerminalPanel />
      </div>
    </div>
  );
};

export const ProjectWorkspaceView = () => {
  const { projectId, partitionKey, appId } = useParams<{
    projectId: string;
    partitionKey?: string;
    appId?: string;
  }>();

  const { data: linkInfo, isLoading } = useQuery({
    queryKey: ['workspace-link', projectId],
    queryFn: () => workspaceApi.getWorkspaceLink(projectId!),
    enabled: !!projectId
  });

  if (!projectId) return null;
  if (isLoading) return <Loading />;

  return (
    <ProjectWorkspaceProvider
      projectId={projectId}
      initialWorkspacePath={linkInfo?.workspace_path || null}
      initialPartitionKey={partitionKey}
      initialAppId={appId}
    >
      <ProjectWorkspaceInner />
    </ProjectWorkspaceProvider>
  );
};
