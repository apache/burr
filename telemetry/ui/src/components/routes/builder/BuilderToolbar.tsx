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

import { useEffect, useRef, useState } from 'react';
import {
  PlusIcon,
  ShieldCheckIcon,
  ArrowDownTrayIcon,
  FolderOpenIcon,
  DocumentArrowDownIcon,
  TrashIcon
} from '@heroicons/react/24/outline';
import { NodeType } from '../../../utils/codeGenerator';
import { NodeTypePicker } from './NodeTypePicker';
import {
  workspaceApi,
  BuilderProjectSummary
} from '../../../api/workspaceApi';

export const BuilderToolbar = (props: {
  onAddNode: (nodeType: NodeType) => void;
  onValidate: () => void;
  validationCount: number;
  projectName: string;
  onProjectNameChange: (name: string) => void;
  onSave: () => void;
  onLoad: (graphJson: string) => void;
  onNew: () => void;
}) => {
  const [pickerOpen, setPickerOpen] = useState(false);
  const [fileMenuOpen, setFileMenuOpen] = useState(false);
  const [savedProjects, setSavedProjects] = useState<BuilderProjectSummary[]>([]);
  const [showOpenDialog, setShowOpenDialog] = useState(false);
  const addBtnRef = useRef<HTMLButtonElement>(null);
  const fileMenuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (fileMenuRef.current && !fileMenuRef.current.contains(e.target as Node)) {
        setFileMenuOpen(false);
      }
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, []);

  const loadProjects = async () => {
    const projects = await workspaceApi.listBuilderProjects();
    setSavedProjects(projects);
    setShowOpenDialog(true);
    setFileMenuOpen(false);
  };

  const handleOpen = async (id: string) => {
    const project = await workspaceApi.getBuilderProject(id);
    props.onProjectNameChange(project.name);
    props.onLoad(project.graph_json);
    setShowOpenDialog(false);
  };

  const handleDelete = async (id: string) => {
    await workspaceApi.deleteBuilderProject(id);
    setSavedProjects((prev) => prev.filter((p) => p.id !== id));
  };

  return (
    <>
      <div className="flex items-center gap-2 px-3 py-2 bg-white border-b">
        {/* File menu */}
        <div className="relative" ref={fileMenuRef}>
          <button
            onClick={() => setFileMenuOpen(!fileMenuOpen)}
            className="px-2.5 py-1.5 text-sm text-gray-700 hover:bg-gray-100 rounded-md"
          >
            File
          </button>
          {fileMenuOpen && (
            <div className="absolute top-full left-0 mt-1 bg-white border border-gray-200 rounded-lg shadow-lg z-50 w-48 py-1">
              <button
                onClick={() => { props.onNew(); setFileMenuOpen(false); }}
                className="flex items-center gap-2 w-full px-3 py-1.5 text-sm text-gray-700 hover:bg-gray-50"
              >
                <PlusIcon className="h-4 w-4" /> New Project
              </button>
              <button
                onClick={() => { props.onSave(); setFileMenuOpen(false); }}
                className="flex items-center gap-2 w-full px-3 py-1.5 text-sm text-gray-700 hover:bg-gray-50"
              >
                <DocumentArrowDownIcon className="h-4 w-4" /> Save
              </button>
              <button
                onClick={loadProjects}
                className="flex items-center gap-2 w-full px-3 py-1.5 text-sm text-gray-700 hover:bg-gray-50"
              >
                <FolderOpenIcon className="h-4 w-4" /> Open...
              </button>
              <hr className="my-1 border-gray-100" />
              <button
                onClick={() => {
                  const code = document.querySelector('.monaco-editor')?.textContent || '';
                  const blob = new Blob([code], { type: 'text/plain' });
                  const url = URL.createObjectURL(blob);
                  const a = document.createElement('a');
                  a.href = url;
                  a.download = `${props.projectName || 'burr_project'}.py`;
                  a.click();
                  URL.revokeObjectURL(url);
                  setFileMenuOpen(false);
                }}
                className="flex items-center gap-2 w-full px-3 py-1.5 text-sm text-gray-700 hover:bg-gray-50"
              >
                <ArrowDownTrayIcon className="h-4 w-4" /> Download .py
              </button>
            </div>
          )}
        </div>

        <div className="h-4 w-px bg-gray-200" />

        {/* Project name */}
        <input
          type="text"
          value={props.projectName}
          onChange={(e) => props.onProjectNameChange(e.target.value)}
          className="px-2 py-1 text-sm font-medium text-gray-700 bg-transparent border-b border-transparent hover:border-gray-300 focus:border-blue-500 outline-none w-40"
          placeholder="Untitled Project"
        />

        <div className="h-4 w-px bg-gray-200" />

        {/* Add Node */}
        <div className="relative">
          <button
            ref={addBtnRef}
            onClick={() => setPickerOpen(!pickerOpen)}
            className="flex items-center gap-1 px-3 py-1.5 bg-dwlightblue text-white rounded-md text-sm hover:opacity-90"
          >
            <PlusIcon className="h-4 w-4" />
            Add Node
          </button>
          {pickerOpen && (
            <NodeTypePicker
              anchorRef={addBtnRef as React.RefObject<HTMLElement>}
              onSelect={(type) => props.onAddNode(type)}
              onClose={() => setPickerOpen(false)}
            />
          )}
        </div>

        {/* Validation */}
        <button
          onClick={props.onValidate}
          className={`flex items-center gap-1 px-3 py-1.5 rounded-md text-sm border ${
            props.validationCount > 0
              ? 'border-yellow-300 text-yellow-700 bg-yellow-50'
              : 'border-green-300 text-green-700 bg-green-50'
          }`}
        >
          <ShieldCheckIcon className="h-4 w-4" />
          {props.validationCount > 0 ? `${props.validationCount} warnings` : 'Valid'}
        </button>
      </div>

      {/* Open Project Dialog */}
      {showOpenDialog && (
        <div className="fixed inset-0 z-[9999] flex items-center justify-center bg-black/30">
          <div className="bg-white rounded-xl shadow-2xl w-96 max-h-[70vh] flex flex-col">
            <div className="flex items-center justify-between px-4 py-3 border-b">
              <h2 className="text-sm font-semibold text-gray-800">Open Project</h2>
              <button onClick={() => setShowOpenDialog(false)} className="text-gray-400 hover:text-gray-600 text-lg">
                x
              </button>
            </div>
            <div className="flex-1 overflow-y-auto">
              {savedProjects.length === 0 && (
                <div className="px-4 py-8 text-sm text-gray-400 text-center">No saved projects</div>
              )}
              {savedProjects.map((p) => (
                <div
                  key={p.id}
                  className="flex items-center justify-between px-4 py-2.5 hover:bg-gray-50 border-b border-gray-100"
                >
                  <button
                    onClick={() => handleOpen(p.id)}
                    className="flex-1 text-left"
                  >
                    <div className="text-sm font-medium text-gray-700">{p.name}</div>
                    <div className="text-xs text-gray-400">
                      {new Date(p.updated_at * 1000).toLocaleString()}
                    </div>
                  </button>
                  <button
                    onClick={() => handleDelete(p.id)}
                    className="p-1 text-gray-300 hover:text-red-500"
                  >
                    <TrashIcon className="h-4 w-4" />
                  </button>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}
    </>
  );
};
