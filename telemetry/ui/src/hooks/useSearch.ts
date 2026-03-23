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

import { useMemo, useState } from 'react';
import Fuse from 'fuse.js';
import { ApplicationModel } from '../api';

export type SearchableItem = {
  type: 'action' | 'state_key' | 'condition';
  name: string;
  context: string;
  projectId: string;
  appId?: string;
};

export const buildSearchIndex = (
  projectId: string,
  applications: Map<string, ApplicationModel>
): SearchableItem[] => {
  const items: SearchableItem[] = [];

  applications.forEach((app, appId) => {
    for (const action of app.actions) {
      items.push({
        type: 'action',
        name: action.name,
        context: `reads: ${action.reads.join(', ')} | writes: ${action.writes.join(', ')}`,
        projectId,
        appId
      });

      for (const key of [...action.reads, ...action.writes]) {
        items.push({
          type: 'state_key',
          name: key,
          context: `Used by action: ${action.name}`,
          projectId,
          appId
        });
      }
    }

    for (const transition of app.transitions) {
      if (transition.condition && transition.condition !== 'default') {
        items.push({
          type: 'condition',
          name: transition.condition,
          context: `${transition.from_} -> ${transition.to}`,
          projectId,
          appId
        });
      }
    }
  });

  return items;
};

export const useSearch = (items: SearchableItem[]) => {
  const [query, setQuery] = useState('');

  const fuse = useMemo(
    () =>
      new Fuse(items, {
        keys: ['name', 'context'],
        threshold: 0.3,
        includeScore: true
      }),
    [items]
  );

  const results = useMemo(() => {
    if (!query.trim()) return [];
    return fuse.search(query, { limit: 50 }).map((r) => r.item);
  }, [query, fuse]);

  return { query, setQuery, results };
};
