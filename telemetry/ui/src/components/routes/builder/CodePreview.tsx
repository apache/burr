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

export const CodePreview = (props: { code: string }) => {
  const copyToClipboard = () => {
    navigator.clipboard.writeText(props.code);
  };

  return (
    <div className="flex flex-col h-full">
      <div className="flex items-center justify-between px-3 py-2 bg-gray-100 border-b">
        <span className="text-sm font-semibold text-gray-600">Generated Python</span>
        <button
          onClick={copyToClipboard}
          className="text-xs text-dwlightblue hover:underline"
        >
          Copy
        </button>
      </div>
      <div className="flex-1 overflow-auto">
        <SyntaxHighlighter
          language="python"
          style={base16AteliersulphurpoolLight}
          wrapLines={true}
          wrapLongLines={true}
          className="!m-0 !text-sm"
        >
          {props.code}
        </SyntaxHighlighter>
      </div>
    </div>
  );
};
