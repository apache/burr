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

import { useEffect, useRef, useState, useMemo } from 'react';
import { createPortal } from 'react-dom';
import {
  BoltIcon,
  ArrowDownTrayIcon,
  FlagIcon,
  SparklesIcon,
  GlobeAltIcon,
  CodeBracketIcon,
  SignalIcon,
  ArrowPathIcon,
  ArrowsRightLeftIcon,
  MagnifyingGlassIcon
} from '@heroicons/react/24/outline';
import { NodeType, NODE_TYPE_META } from '../../../utils/codeGenerator';

// eslint-disable-next-line @typescript-eslint/no-explicit-any
const NODE_TYPE_ICONS: Record<NodeType, React.ComponentType<any>> = {
  action: BoltIcon,
  input: ArrowDownTrayIcon,
  result: FlagIcon,
  llm_call: SparklesIcon,
  api_call: GlobeAltIcon,
  code: CodeBracketIcon,
  streaming: SignalIcon,
  loop: ArrowPathIcon,
  router: ArrowsRightLeftIcon
};

type Category = 'all' | 'io' | 'logic' | 'integrations';

const CATEGORIES: { id: Category; label: string; types: NodeType[] }[] = [
  { id: 'all', label: 'All', types: [] },
  { id: 'io', label: 'I/O', types: ['input', 'result', 'code'] },
  { id: 'logic', label: 'Logic', types: ['action', 'loop', 'router'] },
  { id: 'integrations', label: 'Integrations', types: ['llm_call', 'api_call', 'streaming'] }
];

export const NodeTypePicker = (props: {
  onSelect: (nodeType: NodeType) => void;
  onClose: () => void;
  anchorRef?: React.RefObject<HTMLElement>;
}) => {
  const ref = useRef<HTMLDivElement>(null);
  const searchRef = useRef<HTMLInputElement>(null);
  const [search, setSearch] = useState('');
  const [activeCategory, setActiveCategory] = useState<Category>('all');
  const [pos, setPos] = useState<{ top: number; left: number }>({ top: 0, left: 0 });

  // Continuously track anchor position so picker follows during pan/zoom
  useEffect(() => {
    let rafId: number;
    const update = () => {
      if (props.anchorRef?.current) {
        const rect = props.anchorRef.current.getBoundingClientRect();
        setPos((prev) => {
          const newTop = rect.bottom + 4;
          const newLeft = rect.left + rect.width / 2 - 144;
          if (Math.abs(prev.top - newTop) < 0.5 && Math.abs(prev.left - newLeft) < 0.5) return prev;
          return { top: newTop, left: newLeft };
        });
      }
      rafId = requestAnimationFrame(update);
    };
    rafId = requestAnimationFrame(update);
    return () => cancelAnimationFrame(rafId);
  }, [props.anchorRef]);

  // Close on outside click
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        props.onClose();
      }
    };
    // Use setTimeout to avoid the opening click triggering close
    const timer = setTimeout(() => {
      document.addEventListener('mousedown', handler);
    }, 10);
    return () => {
      clearTimeout(timer);
      document.removeEventListener('mousedown', handler);
    };
  }, [props.onClose]);

  useEffect(() => {
    setTimeout(() => searchRef.current?.focus(), 50);
  }, []);

  // Close on Escape
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') props.onClose();
    };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [props.onClose]);

  const filteredTypes = useMemo(() => {
    const allTypes = Object.entries(NODE_TYPE_META) as [NodeType, (typeof NODE_TYPE_META)[NodeType]][];

    return allTypes.filter(([type, meta]) => {
      const matchesSearch =
        !search ||
        meta.label.toLowerCase().includes(search.toLowerCase()) ||
        meta.description.toLowerCase().includes(search.toLowerCase()) ||
        type.toLowerCase().includes(search.toLowerCase());

      const matchesCategory =
        activeCategory === 'all' ||
        CATEGORIES.find((c) => c.id === activeCategory)?.types.includes(type);

      return matchesSearch && matchesCategory;
    });
  }, [search, activeCategory]);

  const content = (
    <div
      ref={ref}
      className="fixed z-[9999] bg-white border border-gray-200 rounded-xl shadow-2xl w-72 overflow-hidden"
      style={{ top: pos.top, left: Math.max(8, pos.left) }}
      onClick={(e) => e.stopPropagation()}
      onMouseDown={(e) => e.stopPropagation()}
    >
      {/* Search */}
      <div className="p-2 border-b border-gray-100">
        <div className="flex items-center gap-2 bg-gray-50 rounded-lg px-2.5 py-1.5">
          <MagnifyingGlassIcon className="h-4 w-4 text-gray-400 shrink-0" />
          <input
            ref={searchRef}
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search steps..."
            className="flex-1 bg-transparent text-sm outline-none placeholder-gray-400"
          />
        </div>
      </div>

      {/* Category tabs */}
      {!search && (
        <div className="flex px-2 pt-1.5 gap-0.5 border-b border-gray-100">
          {CATEGORIES.map((cat) => (
            <button
              key={cat.id}
              onClick={() => setActiveCategory(cat.id)}
              className={`px-2.5 py-1 text-xs rounded-t-md transition-colors ${
                activeCategory === cat.id
                  ? 'bg-gray-100 text-gray-900 font-medium'
                  : 'text-gray-500 hover:text-gray-700'
              }`}
            >
              {cat.label}
            </button>
          ))}
        </div>
      )}

      {/* Results */}
      <div className="max-h-[280px] overflow-y-auto py-1">
        {filteredTypes.length === 0 && (
          <div className="px-3 py-4 text-xs text-gray-400 text-center">No matching steps</div>
        )}
        {filteredTypes.map(([type, meta]) => {
          const Icon = NODE_TYPE_ICONS[type];
          return (
            <button
              key={type}
              onClick={(e) => {
                e.stopPropagation();
                e.preventDefault();
                props.onSelect(type);
                props.onClose();
              }}
              onMouseDown={(e) => e.stopPropagation()}
              className="flex items-center gap-3 w-full px-3 py-2 text-left hover:bg-gray-50 transition-colors"
            >
              <div
                className={`w-8 h-8 rounded-lg flex items-center justify-center ${meta.color} ${meta.borderColor} border shrink-0`}
              >
                <Icon className="h-4 w-4 text-gray-600" />
              </div>
              <div className="min-w-0 flex-1">
                <div className="text-sm font-medium text-gray-800">{meta.label}</div>
                <div className="text-[11px] text-gray-400 truncate">{meta.description}</div>
              </div>
            </button>
          );
        })}
      </div>
    </div>
  );

  return createPortal(content, document.body);
};
