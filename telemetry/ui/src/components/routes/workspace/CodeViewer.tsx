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

import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter';
import { base16AteliersulphurpoolLight } from 'react-syntax-highlighter/dist/esm/styles/prism';
import { ClipboardIcon, CheckIcon } from '@heroicons/react/24/outline';
import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { workspaceApi } from '../../../api/workspaceApi';

interface CodeViewerProps {
  workspace: string;
  filePath: string;
}

export const CodeViewer = ({ workspace, filePath }: CodeViewerProps) => {
  const [copied, setCopied] = useState(false);

  const { data, isLoading, error } = useQuery({
    queryKey: ['workspace-file', workspace, filePath],
    queryFn: () => workspaceApi.getFileContent(workspace, filePath),
    enabled: !!filePath
  });

  const copyToClipboard = () => {
    if (data?.content) {
      navigator.clipboard.writeText(data.content);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  };

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-full text-gray-400 text-sm">
        Loading...
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex items-center justify-center h-full text-red-500 text-sm">
        {error instanceof Error ? error.message : 'Failed to load file'}
      </div>
    );
  }

  if (!data) {
    return (
      <div className="flex items-center justify-center h-full text-gray-400 text-sm">
        Select a file to view
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full">
      <div className="flex items-center justify-between px-3 py-2 bg-gray-50 border-b border-gray-200">
        <span className="text-sm text-gray-600 font-mono truncate">{filePath}</span>
        <button
          onClick={copyToClipboard}
          className="p-1 rounded hover:bg-gray-200"
          title="Copy to clipboard"
        >
          {copied ? (
            <CheckIcon className="h-4 w-4 text-green-500" />
          ) : (
            <ClipboardIcon className="h-4 w-4 text-gray-400" />
          )}
        </button>
      </div>
      <div className="flex-1 overflow-auto">
        <SyntaxHighlighter
          language={data.language}
          style={base16AteliersulphurpoolLight}
          showLineNumbers
          customStyle={{ margin: 0, minHeight: '100%', fontSize: '13px' }}
        >
          {data.content}
        </SyntaxHighlighter>
      </div>
    </div>
  );
};
