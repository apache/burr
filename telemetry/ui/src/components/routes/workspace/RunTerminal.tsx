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
import { Link } from 'react-router-dom';
import { StopIcon } from '@heroicons/react/24/outline';
import { ProcessInfo, ProcessOutputEvent, workspaceApi } from '../../../api/workspaceApi';

interface RunTerminalProps {
  process: ProcessInfo;
  onStopped: () => void;
}

interface OutputLine {
  type: 'stdout' | 'stderr' | 'exit';
  text: string;
}

// Basic ANSI color codes to CSS classes
function ansiToSpans(text: string): JSX.Element[] {
  const parts: JSX.Element[] = [];
  // eslint-disable-next-line no-control-regex
  const ansiRegex = new RegExp('\\x1b\\[([0-9;]*)m', 'g');
  let lastIndex = 0;
  let currentClass = '';
  let ansiMatch;
  let key = 0;

  while ((ansiMatch = ansiRegex.exec(text)) !== null) {
    if (ansiMatch.index > lastIndex) {
      parts.push(
        <span key={key++} className={currentClass}>
          {text.slice(lastIndex, ansiMatch.index)}
        </span>
      );
    }
    const codes = ansiMatch[1].split(';').map(Number);
    for (const code of codes) {
      if (code === 0) currentClass = '';
      else if (code === 1) currentClass = 'font-bold';
      else if (code >= 30 && code <= 37) currentClass = ansiColorClass(code - 30);
      else if (code >= 90 && code <= 97) currentClass = ansiColorClass(code - 90, true);
    }
    lastIndex = ansiRegex.lastIndex;
  }
  if (lastIndex < text.length) {
    parts.push(
      <span key={key++} className={currentClass}>
        {text.slice(lastIndex)}
      </span>
    );
  }
  return parts.length > 0 ? parts : [<span key={0}>{text}</span>];
}

function ansiColorClass(index: number, bright = false): string {
  const colors = [
    'text-gray-900',
    'text-red-600',
    'text-green-600',
    'text-yellow-600',
    'text-blue-600',
    'text-purple-600',
    'text-cyan-600',
    'text-gray-100'
  ];
  const brightColors = [
    'text-gray-600',
    'text-red-400',
    'text-green-400',
    'text-yellow-400',
    'text-blue-400',
    'text-purple-400',
    'text-cyan-400',
    'text-white'
  ];
  return (bright ? brightColors : colors)[index] || '';
}

export const RunTerminal = ({ process: proc, onStopped }: RunTerminalProps) => {
  const [lines, setLines] = useState<OutputLine[]>([]);
  const [exited, setExited] = useState(false);
  const [exitCode, setExitCode] = useState<number | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    setLines([]);
    setExited(false);
    setExitCode(null);

    const ctrl = workspaceApi.streamProcessOutput(
      proc.pid,
      (event: ProcessOutputEvent) => {
        if (event.type === 'exit') {
          setExited(true);
          setExitCode(parseInt(event.data, 10));
        } else {
          setLines((prev) => [...prev, { type: event.type, text: event.data }]);
        }
      },
      () => {
        // SSE connection error, mark as exited
        setExited(true);
      }
    );
    abortRef.current = ctrl;

    return () => {
      ctrl.abort();
    };
  }, [proc.pid]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [lines, exited]);

  const handleStop = async () => {
    try {
      await workspaceApi.stopProcess(proc.pid);
    } catch {
      // process may have already exited
    }
    onStopped();
  };

  return (
    <div className="flex flex-col h-full bg-gray-900">
      <div className="flex items-center justify-between px-3 py-1.5 bg-gray-800 border-b border-gray-700">
        <span className="text-xs text-gray-300 font-mono truncate">{proc.script_path}</span>
        <div className="flex items-center gap-2">
          {exited && exitCode !== null && (
            <span
              className={`text-xs px-1.5 py-0.5 rounded ${exitCode === 0 ? 'bg-green-900 text-green-300' : 'bg-red-900 text-red-300'}`}
            >
              exit {exitCode}
            </span>
          )}
          {exited && (
            <Link to="/projects" className="text-xs text-blue-400 hover:text-blue-300 underline">
              View runs in Projects
            </Link>
          )}
          {!exited && (
            <button
              onClick={handleStop}
              className="p-1 rounded hover:bg-gray-700"
              title="Stop process"
            >
              <StopIcon className="h-4 w-4 text-red-400" />
            </button>
          )}
        </div>
      </div>
      <div className="flex-1 overflow-auto p-3 font-mono text-xs leading-relaxed">
        {lines.map((line, i) => (
          <div key={i} className={line.type === 'stderr' ? 'text-red-400' : 'text-gray-100'}>
            {ansiToSpans(line.text)}
          </div>
        ))}
        <div ref={bottomRef} />
      </div>
    </div>
  );
};
