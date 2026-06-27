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

import { useState, useCallback } from 'react';
import {
  FolderIcon,
  FolderOpenIcon,
  DocumentIcon,
  DocumentTextIcon,
  ChevronRightIcon,
  PlayIcon
} from '@heroicons/react/24/outline';
import { FileEntry, workspaceApi } from '../../../api/workspaceApi';

interface FileExplorerProps {
  workspace: string;
  rootEntries: FileEntry[];
  onSelectFile: (relativePath: string) => void;
  onRunScript: (relativePath: string) => void;
}

interface TreeNodeProps {
  entry: FileEntry;
  workspace: string;
  onSelectFile: (path: string) => void;
  onRunScript: (path: string) => void;
  depth: number;
}

const TreeNode = ({ entry, workspace, onSelectFile, onRunScript, depth }: TreeNodeProps) => {
  const [expanded, setExpanded] = useState(false);
  const [children, setChildren] = useState<FileEntry[]>([]);
  const [loading, setLoading] = useState(false);
  const [hovered, setHovered] = useState(false);

  const toggle = useCallback(async () => {
    if (!entry.is_dir) {
      onSelectFile(entry.path);
      return;
    }
    if (!expanded && children.length === 0) {
      setLoading(true);
      try {
        const entries = await workspaceApi.getFileTree(workspace, entry.path);
        setChildren(entries);
      } catch {
        // silently fail
      }
      setLoading(false);
    }
    setExpanded(!expanded);
  }, [entry, workspace, expanded, children.length, onSelectFile]);

  const Icon = entry.is_dir ? (expanded ? FolderOpenIcon : FolderIcon) : getFileIcon(entry);

  return (
    <div>
      <div
        className="flex items-center gap-1 py-0.5 px-1 rounded hover:bg-gray-100 cursor-pointer group"
        style={{ paddingLeft: `${depth * 16 + 4}px` }}
        onClick={toggle}
        onMouseEnter={() => setHovered(true)}
        onMouseLeave={() => setHovered(false)}
      >
        {entry.is_dir && (
          <ChevronRightIcon
            className={`h-3 w-3 text-gray-400 shrink-0 transition-transform ${expanded ? 'rotate-90' : ''}`}
          />
        )}
        {!entry.is_dir && <span className="w-3" />}
        <Icon className="h-4 w-4 text-gray-500 shrink-0" />
        <span className="text-sm text-gray-700 truncate">{entry.name}</span>
        {entry.has_burr_app && (
          <span className="text-xs bg-blue-100 text-blue-700 px-1.5 py-0.5 rounded font-medium ml-1">
            Burr
          </span>
        )}
        {loading && <span className="text-xs text-gray-400 ml-auto">...</span>}
        {hovered && entry.is_python && !entry.is_dir && (
          <button
            onClick={(e) => {
              e.stopPropagation();
              onRunScript(entry.path);
            }}
            className="ml-auto p-0.5 rounded hover:bg-green-100"
            title="Run script"
          >
            <PlayIcon className="h-3.5 w-3.5 text-green-600" />
          </button>
        )}
      </div>
      {expanded &&
        children.map((child) => (
          <TreeNode
            key={child.path}
            entry={child}
            workspace={workspace}
            onSelectFile={onSelectFile}
            onRunScript={onRunScript}
            depth={depth + 1}
          />
        ))}
    </div>
  );
};

function getFileIcon(entry: FileEntry) {
  if (entry.is_python) return DocumentTextIcon;
  return DocumentIcon;
}

export const FileExplorer = ({
  workspace,
  rootEntries,
  onSelectFile,
  onRunScript
}: FileExplorerProps) => {
  return (
    <div className="h-full overflow-y-auto py-2">
      {rootEntries.map((entry) => (
        <TreeNode
          key={entry.path}
          entry={entry}
          workspace={workspace}
          onSelectFile={onSelectFile}
          onRunScript={onRunScript}
          depth={0}
        />
      ))}
    </div>
  );
};
