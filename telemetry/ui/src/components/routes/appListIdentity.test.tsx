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

import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from 'react-query';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router';
import { afterEach, describe, expect, test, vi, beforeAll } from 'vitest';
import { DefaultService } from '../../api';
import type { ApplicationSummary } from '../../api';
import { AppList, AppListTable } from './AppList';
import { appDetailPath, applicationIdentityKey, partitionQueryArgs } from '../../partitionIdentity';

vi.mock('react-router-dom', async () => {
  const mod = await vi.importActual('react-router');
  return mod as typeof import('react-router-dom');
});

beforeAll(() => {
  vi.stubGlobal(
    'ResizeObserver',
    class {
      observe() {}
      disconnect() {}
    }
  );
});

afterEach(() => {
  vi.restoreAllMocks();
});

const app = (
  appId: string,
  partitionKey: string | null,
  numSteps: number,
  spawningParentPointer: ApplicationSummary['spawning_parent_pointer'] = null
): ApplicationSummary => ({
  app_id: appId,
  partition_key: partitionKey,
  first_written: '2026-01-01T00:00:00Z',
  last_written: '2026-01-01T00:00:01Z',
  num_steps: numSteps,
  tags: {},
  parent_pointer: null,
  spawning_parent_pointer: spawningParentPointer
});

const LocationDisplay = () => {
  const location = useLocation();
  return <div data-testid="location">{location.pathname + location.search}</div>;
};

describe('partition identity after fix', () => {
  test('same app_id with different partitions has unique React keys', () => {
    const errors: string[] = [];
    const spy = vi.spyOn(console, 'error').mockImplementation((...args) => {
      errors.push(args.join(' '));
    });
    render(
      <MemoryRouter>
        <AppListTable apps={[app('shared', 'A', 1), app('shared', 'B', 2)]} projectId="project" />
      </MemoryRouter>
    );
    expect(screen.getAllByText('shared')).toHaveLength(2);
    expect(errors.some((message) => message.includes('same key'))).toBe(false);
    spy.mockRestore();
  });

  test('parent map distinguishes parent partitions with the same app_id', () => {
    const parentA = app('parent', 'A', 1);
    const parentB = app('parent', 'B', 1);
    const children = [
      app('child-A', 'A', 1, {
        type: 'pointer_data',
        app_id: 'parent',
        sequence_id: 0,
        partition_key: 'A'
      }),
      app('child-B', 'B', 1, {
        type: 'pointer_data',
        app_id: 'parent',
        sequence_id: 0,
        partition_key: 'B'
      })
    ];
    render(
      <MemoryRouter>
        <AppListTable apps={[parentA, parentB, ...children]} projectId="project" />
      </MemoryRouter>
    );
    expect(screen.getAllByText('(1)')).toHaveLength(2);
  });

  test('null and empty partitions navigate to unambiguous URLs', () => {
    render(
      <MemoryRouter initialEntries={['/partition-identity/project/apps']}>
        <AppListTable apps={[app('shared', null, 1), app('shared', '', 2)]} projectId="project" />
        <LocationDisplay />
      </MemoryRouter>
    );
    const rows = screen.getAllByText('shared');
    fireEvent.click(rows[0]);
    expect(screen.getByTestId('location').textContent).toBe(
      '/partition-identity/project/app/shared?none_partition=true'
    );
    fireEvent.click(rows[1]);
    expect(screen.getByTestId('location').textContent).toBe(
      '/partition-identity/project/app/shared?partition_key='
    );
  });

  test('identity helpers do not collide', () => {
    expect(applicationIdentityKey('a', null)).not.toBe(applicationIdentityKey('a', 'null'));
    expect(applicationIdentityKey('a', null)).not.toBe(applicationIdentityKey('a', '__none__'));
    expect(applicationIdentityKey('a', '')).not.toBe(applicationIdentityKey('a', null));
    expect(partitionQueryArgs('')).toEqual({ partitionKey: '' });
    expect(partitionQueryArgs(null)).toEqual({ nonePartition: true });
    expect(appDetailPath('p', 'a', '__none__')).toContain('partition_key=__none__');
  });
});

describe('AppList request-parameter compatibility', () => {
  const renderAppListAt = (pathname: string) =>
    render(
      <QueryClientProvider
        client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
      >
        <MemoryRouter initialEntries={[pathname]}>
          <Routes>
            <Route path="/project/:projectId/:partitionKey" element={<AppList />} />
            <Route path="/partition-identity/:projectId/apps" element={<AppList />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>
    );

  const mockListApps = () =>
    vi.spyOn(DefaultService, 'listAppsByPartitionQuery').mockResolvedValue({
      applications: [],
      total: 0,
      has_another_page: false
    });

  test('legacy null segment is queried as the literal string "null"', async () => {
    const spy = mockListApps();
    renderAppListAt('/project/p/null');
    await waitFor(() => expect(spy).toHaveBeenCalled());
    expect(spy).toHaveBeenCalledWith('p', 'null', undefined, 100, 0);
  });

  test('legacy __none__ segment keeps the historical no-filter query', async () => {
    const spy = mockListApps();
    renderAppListAt('/project/p/__none__');
    await waitFor(() => expect(spy).toHaveBeenCalled());
    expect(spy).toHaveBeenCalledWith('p', undefined, undefined, 100, 0);
  });

  test('identity route none_partition=true queries only the None partition', async () => {
    const spy = mockListApps();
    renderAppListAt('/partition-identity/p/apps?none_partition=true');
    await waitFor(() => expect(spy).toHaveBeenCalled());
    expect(spy).toHaveBeenCalledWith('p', undefined, true, 100, 0);
  });
});
