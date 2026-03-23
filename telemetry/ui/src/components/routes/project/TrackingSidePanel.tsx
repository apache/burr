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

import { useQuery } from '@tanstack/react-query';
import { DefaultService } from '../../../api';
import { useProjectWorkspace } from './ProjectWorkspaceContext';
import { Loading } from '../../common/loading';
import { DateTimeDisplay } from '../../common/dates';

const SENTINEL = '__none__';

export const TrackingSidePanel = () => {
  const { projectId, openTab } = useProjectWorkspace();

  const { data, isLoading } = useQuery({
    queryKey: ['apps', projectId, SENTINEL, 0, 100],
    queryFn: () =>
      DefaultService.getAppsApiV0ProjectIdPartitionKeyAppsGet(projectId, SENTINEL, 100, 0)
  });

  if (isLoading) return <Loading />;

  const apps = data?.applications || [];

  return (
    <div className="flex flex-col h-full">
      <div className="px-3 py-2 border-b border-gray-200">
        <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-wide">Runs</h3>
      </div>
      <div className="flex-1 overflow-y-auto">
        {apps.length === 0 && (
          <div className="px-3 py-4 text-xs text-gray-400">No runs yet</div>
        )}
        {apps.map((app) => (
          <button
            key={app.app_id}
            onClick={() =>
              openTab({
                id: `tracking:${app.app_id}`,
                type: 'tracking',
                label: app.app_id,
                appId: app.app_id,
                partitionKey: app.partition_key || undefined
              })
            }
            className="w-full text-left px-3 py-2 hover:bg-gray-50 border-b border-gray-100 transition-colors"
          >
            <div className="text-sm text-gray-700 truncate font-mono">{app.app_id}</div>
            <div className="flex items-center gap-2 mt-0.5">
              <span className="text-xs text-gray-400">{app.num_steps} steps</span>
              <span className="text-xs text-gray-400">
                <DateTimeDisplay date={app.last_written} mode="short" />
              </span>
            </div>
          </button>
        ))}
      </div>
    </div>
  );
};
