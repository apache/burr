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

import { useCallback, useEffect, useRef, useState } from 'react';
import { useParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import Editor, { OnMount } from '@monaco-editor/react';
import {
  DocumentTextIcon,
  XMarkIcon,
  ChevronRightIcon,
  FolderIcon,
  FolderOpenIcon
} from '@heroicons/react/24/outline';
import { DefaultService } from '../../../api';
import { useBuilderState } from '../../../hooks/useBuilderState';
import { BuilderGraph } from './BuilderGraph';
import { BuilderToolbar } from './BuilderToolbar';
import { NodeEditor } from './NodeEditor';
import { NodeType, ProjectFile } from '../../../utils/codeGenerator';
import { parsePythonCode, buildTreeFromParsed } from '../../../utils/codeParser';
import { FileEntry, workspaceApi } from '../../../api/workspaceApi';

type OpenTab = {
  name: string;
  language: string;
  content: string;
  source: 'generated' | 'workspace';
  path?: string; // workspace relative path
  modified?: boolean;
};

// Mini file explorer for the editor sidebar
const EditorFileExplorer = (props: {
  generatedFiles: ProjectFile[];
  workspacePath: string | null;
  onOpenFile: (tab: OpenTab) => void;
}) => {
  const [expanded, setExpanded] = useState(true);
  const [wsExpanded, setWsExpanded] = useState(false);
  const [wsFiles, setWsFiles] = useState<FileEntry[]>([]);
  const [wsSubFiles, setWsSubFiles] = useState<Record<string, FileEntry[]>>({});

  useEffect(() => {
    if (props.workspacePath && wsExpanded) {
      workspaceApi.getFileTree(props.workspacePath).then(setWsFiles);
    }
  }, [props.workspacePath, wsExpanded]);

  const loadSubDir = async (path: string) => {
    if (!props.workspacePath || wsSubFiles[path]) return;
    const entries = await workspaceApi.getFileTree(props.workspacePath, path);
    setWsSubFiles((prev) => ({ ...prev, [path]: entries }));
  };

  const openWsFile = async (entry: FileEntry) => {
    if (!props.workspacePath || entry.is_dir) return;
    const data = await workspaceApi.getFileContent(props.workspacePath, entry.path);
    props.onOpenFile({
      name: entry.name,
      language: data.language,
      content: data.content,
      source: 'workspace',
      path: entry.path
    });
  };

  const langMap: Record<string, string> = {
    py: 'python', js: 'javascript', ts: 'typescript', json: 'json',
    yaml: 'yaml', yml: 'yaml', toml: 'toml', md: 'markdown', txt: 'plaintext'
  };

  return (
    <div className="w-48 shrink-0 border-r border-gray-200 bg-gray-50 text-xs overflow-y-auto">
      {/* Generated files */}
      <button
        onClick={() => setExpanded(!expanded)}
        className="flex items-center gap-1 w-full px-2 py-1.5 text-[10px] font-bold text-gray-500 uppercase tracking-wider hover:bg-gray-100"
      >
        <ChevronRightIcon className={`h-3 w-3 transition-transform ${expanded ? 'rotate-90' : ''}`} />
        Generated
      </button>
      {expanded &&
        props.generatedFiles.map((f) => (
          <button
            key={f.name}
            onClick={() =>
              props.onOpenFile({ name: f.name, language: f.language, content: f.content, source: 'generated' })
            }
            className="flex items-center gap-1.5 w-full px-4 py-1 text-gray-600 hover:bg-gray-100 truncate"
          >
            <DocumentTextIcon className="h-3.5 w-3.5 text-gray-400 shrink-0" />
            {f.name}
          </button>
        ))}

      {/* Workspace files */}
      {props.workspacePath && (
        <>
          <button
            onClick={() => setWsExpanded(!wsExpanded)}
            className="flex items-center gap-1 w-full px-2 py-1.5 text-[10px] font-bold text-gray-500 uppercase tracking-wider hover:bg-gray-100 mt-1"
          >
            <ChevronRightIcon className={`h-3 w-3 transition-transform ${wsExpanded ? 'rotate-90' : ''}`} />
            Workspace
          </button>
          {wsExpanded &&
            wsFiles.map((entry) =>
              entry.is_dir ? (
                <div key={entry.path}>
                  <button
                    onClick={() => {
                      if (wsSubFiles[entry.path]) {
                        setWsSubFiles((prev) => {
                          const next = { ...prev };
                          delete next[entry.path];
                          return next;
                        });
                      } else {
                        loadSubDir(entry.path);
                      }
                    }}
                    className="flex items-center gap-1.5 w-full px-4 py-1 text-gray-600 hover:bg-gray-100 truncate"
                  >
                    {wsSubFiles[entry.path] ? (
                      <FolderOpenIcon className="h-3.5 w-3.5 text-gray-400 shrink-0" />
                    ) : (
                      <FolderIcon className="h-3.5 w-3.5 text-gray-400 shrink-0" />
                    )}
                    {entry.name}
                  </button>
                  {wsSubFiles[entry.path]?.map((sub) =>
                    !sub.is_dir ? (
                      <button
                        key={sub.path}
                        onClick={() => openWsFile(sub)}
                        className="flex items-center gap-1.5 w-full px-7 py-1 text-gray-500 hover:bg-gray-100 truncate"
                      >
                        <DocumentTextIcon className="h-3 w-3 text-gray-400 shrink-0" />
                        {sub.name}
                      </button>
                    ) : null
                  )}
                </div>
              ) : (
                <button
                  key={entry.path}
                  onClick={() => openWsFile(entry)}
                  className="flex items-center gap-1.5 w-full px-4 py-1 text-gray-600 hover:bg-gray-100 truncate"
                >
                  <DocumentTextIcon className="h-3.5 w-3.5 text-gray-400 shrink-0" />
                  {entry.name}
                </button>
              )
            )}
        </>
      )}
    </div>
  );
};

export const BuilderView = () => {
  const { projectId, appId } = useParams<{ projectId?: string; appId?: string }>();
  const [projectName, setProjectName] = useState('Untitled Project');

  const builder = useBuilderState();

  const editSourceRef = useRef<'graph' | 'editor'>('graph');
  const [editorOverrides, setEditorOverrides] = useState<Record<string, string>>({});
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [parseError, setParseError] = useState<string | null>(null);

  // Cleanup debounce on unmount
  useEffect(() => {
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
  }, []);

  // Open tabs
  const [openTabs, setOpenTabs] = useState<OpenTab[]>([]);
  const [activeTabName, setActiveTabName] = useState<string | null>(null);

  // Workspace link
  const { data: linkInfo } = useQuery({
    queryKey: ['workspace-link', projectId],
    queryFn: () => workspaceApi.getWorkspaceLink(projectId!),
    enabled: !!projectId
  });
  const workspacePath = linkInfo?.workspace_path || null;

  const { data: appData } = useQuery({
    queryKey: ['steps', appId],
    queryFn: () =>
      DefaultService.getApplicationLogsApiV0ProjectIdAppIdPartitionKeyAppsGet(projectId!, appId!, '__none__'),
    enabled: !!projectId && !!appId
  });

  const [imported, setImported] = useState(false);
  useEffect(() => {
    if (appData && !imported) {
      builder.importFromApplication(appData.application);
      setImported(true);
    }
  }, [appData, imported, builder]);

  // Auto-open actions.py on first load
  useEffect(() => {
    if (builder.projectFiles.length > 0 && openTabs.length === 0) {
      const actionsFile = builder.projectFiles[0];
      const tab: OpenTab = {
        name: actionsFile.name,
        language: actionsFile.language,
        content: actionsFile.content,
        source: 'generated'
      };
      setOpenTabs([tab]);
      setActiveTabName(tab.name);
    }
  }, [builder.projectFiles]);

  const handleAddNode = useCallback(
    (nodeType: NodeType) => {
      editSourceRef.current = 'graph';
      setEditorOverrides({});
      builder.addNode({ x: 0, y: 0 }, nodeType);
    },
    [builder]
  );

  const handleSave = useCallback(async () => {
    const graphJson = JSON.stringify(builder.rootNode);
    await workspaceApi.saveBuilderProject(projectName, graphJson);
  }, [builder.rootNode, projectName]);

  const handleLoad = useCallback(
    (graphJson: string) => {
      try {
        const parsed = JSON.parse(graphJson);
        builder.setRootNode(parsed);
        editSourceRef.current = 'graph';
        setEditorOverrides({});
        setOpenTabs([]);
        setActiveTabName(null);
      } catch {
        // invalid JSON
      }
    },
    [builder]
  );

  const handleNew = useCallback(() => {
    builder.setRootNode(null);
    setProjectName('Untitled Project');
    editSourceRef.current = 'graph';
    setEditorOverrides({});
    setOpenTabs([]);
    setActiveTabName(null);
  }, [builder]);

  // Ctrl+S to save
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key === 's') {
        e.preventDefault();
        handleSave();
      }
    };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [handleSave]);

  const getTabKey = (t: OpenTab) => t.path || t.name;

  const openFile = useCallback((tab: OpenTab) => {
    const key = getTabKey(tab);
    setOpenTabs((prev) => {
      const exists = prev.find((t) => getTabKey(t) === key);
      if (exists) return prev;
      return [...prev, tab];
    });
    setActiveTabName(key);
  }, []);

  const closeTab = useCallback(
    (key: string) => {
      setOpenTabs((prev) => {
        const filtered = prev.filter((t) => getTabKey(t) !== key);
        if (activeTabName === key) {
          setActiveTabName(filtered.length > 0 ? getTabKey(filtered[filtered.length - 1]) : null);
        }
        return filtered;
      });
    },
    [activeTabName]
  );

  const activeTab = openTabs.find((t) => getTabKey(t) === activeTabName);

  // Get content for active tab (generated files update from graph)
  const getTabContent = (tab: OpenTab): string => {
    if (tab.source === 'generated') {
      if (editSourceRef.current === 'editor' && editorOverrides[tab.name] !== undefined) {
        return editorOverrides[tab.name];
      }
      const gen = builder.projectFiles.find((f) => f.name === tab.name);
      return gen?.content || tab.content;
    }
    return editorOverrides[getTabKey(tab)] ?? tab.content;
  };

  const getTabLanguage = (tab: OpenTab): string => {
    if (tab.source === 'generated') {
      return builder.projectFiles.find((f) => f.name === tab.name)?.language || tab.language;
    }
    return tab.language;
  };

  const handleEditorChange = useCallback(
    (value: string | undefined) => {
      if (!value || !activeTabName) return;
      editSourceRef.current = 'editor';
      setEditorOverrides((prev) => ({ ...prev, [activeTabName]: value }));

      // Parse for graph sync only on generated Python files
      const tab = openTabs.find((t) => t.name === activeTabName);
      if (!tab || tab.source !== 'generated') return;
      if (activeTabName !== 'actions.py' && activeTabName !== 'app.py') return;

      if (debounceRef.current) clearTimeout(debounceRef.current);
      debounceRef.current = setTimeout(() => {
        const actionsCode =
          activeTabName === 'actions.py'
            ? value
            : editorOverrides['actions.py'] ||
              builder.projectFiles.find((f) => f.name === 'actions.py')?.content ||
              '';
        const appCode =
          activeTabName === 'app.py'
            ? value
            : editorOverrides['app.py'] ||
              builder.projectFiles.find((f) => f.name === 'app.py')?.content ||
              '';

        const parsed = parsePythonCode(actionsCode + '\n\n' + appCode);
        if (parsed.error || parsed.actions.length === 0) {
          setParseError(parsed.error || null);
          return;
        }
        setParseError(null);
        const tree = buildTreeFromParsed(parsed);
        if (tree) builder.setRootFromCode(tree);
      }, 1000);
    },
    [activeTabName, builder, editorOverrides, openTabs]
  );

  const handleEditorMount: OnMount = (editor) => {
    editor.onDidFocusEditorText(() => {
      editSourceRef.current = 'editor';
    });
    editor.onDidBlurEditorText(() => {
      editSourceRef.current = 'graph';
      setEditorOverrides({});
    });
  };

  return (
    <div className="flex flex-col h-full">
      <BuilderToolbar
        onAddNode={handleAddNode}
        onValidate={() => {}}
        validationCount={builder.validationErrors.size}
        projectName={projectName}
        onProjectNameChange={setProjectName}
        onSave={handleSave}
        onLoad={handleLoad}
        onNew={handleNew}
      />

      <div className="flex flex-1 min-h-0">
        {/* Left: Visual Builder */}
        <div className="w-1/2 flex border-r border-gray-200">
          <div className="flex-1">
            <BuilderGraph
              layoutGraph={builder.layoutGraph}
              selectedNodeId={builder.selectedNodeId}
              onSelectNode={(id) => {
                editSourceRef.current = 'graph';
                setEditorOverrides({});
                builder.setSelectedNodeId(id);
              }}
              onInsert={(nodeType, ctx) => {
                editSourceRef.current = 'graph';
                setEditorOverrides({});
                builder.handleInsert(nodeType, ctx);
              }}
              unresolvedReads={builder.validationErrors}
            />
          </div>

          {builder.selectedNode && (
            <NodeEditor
              node={builder.selectedNode}
              onUpdate={(updates) => {
                editSourceRef.current = 'graph';
                setEditorOverrides({});
                builder.updateNode(builder.selectedNode!.id, updates);
              }}
              onDelete={() => {
                editSourceRef.current = 'graph';
                setEditorOverrides({});
                builder.removeNode(builder.selectedNode!.id);
              }}
              unresolvedReads={builder.validationErrors.get(builder.selectedNode.name) || []}
            />
          )}
        </div>

        {/* Right: VS Code-style editor */}
        <div className="w-1/2 flex">
          {/* Mini file explorer */}
          <EditorFileExplorer
            generatedFiles={builder.projectFiles}
            workspacePath={workspacePath}
            onOpenFile={openFile}
          />

          {/* Editor area */}
          <div className="flex-1 flex flex-col min-w-0">
            {/* Tabs */}
            <div className="flex items-center bg-gray-50 border-b border-gray-200 overflow-x-auto shrink-0">
              {openTabs.map((tab) => {
                const key = getTabKey(tab);
                return (
                  <div
                    key={key}
                    onClick={() => setActiveTabName(key)}
                    className={`flex items-center gap-1 px-3 py-1.5 text-xs cursor-pointer border-r border-gray-200 shrink-0 select-none ${
                      key === activeTabName
                        ? 'bg-white text-gray-900 font-medium border-b-2 border-b-blue-500'
                        : 'bg-gray-50 text-gray-500 hover:bg-gray-100'
                    }`}
                  >
                    <DocumentTextIcon className="h-3 w-3 shrink-0" />
                    <span className="truncate max-w-[100px]">{tab.name}</span>
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        closeTab(key);
                      }}
                      className="ml-1 p-0.5 rounded hover:bg-gray-200"
                    >
                      <XMarkIcon className="h-3 w-3" />
                    </button>
                  </div>
                );
              })}
              <div className="flex-1" />
              {parseError && <span className="text-[10px] text-red-500 px-2">Parse error</span>}
            </div>

            {/* Monaco Editor */}
            <div className="flex-1">
              {activeTab ? (
                <Editor
                  key={activeTab.name}
                  defaultLanguage={getTabLanguage(activeTab)}
                  value={getTabContent(activeTab)}
                  theme="vs-light"
                  onChange={handleEditorChange}
                  onMount={handleEditorMount}
                  options={{
                    minimap: { enabled: true },
                    fontSize: 13,
                    lineNumbers: 'on',
                    scrollBeyondLastLine: false,
                    wordWrap: 'on',
                    automaticLayout: true,
                    folding: true,
                    renderLineHighlight: 'all',
                    tabSize: 4
                  }}
                />
              ) : (
                <div className="flex items-center justify-center h-full text-gray-400 text-sm">
                  Open a file from the explorer
                </div>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};
