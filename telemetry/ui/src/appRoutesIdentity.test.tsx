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

import { matchRoutes } from 'react-router-dom';
import { describe, expect, test } from 'vitest';
import { appRoutes } from './App';

const match = (pathname: string) => {
  const result = matchRoutes(appRoutes, pathname);
  return { id: result?.at(-1)?.route.id, params: result?.at(-1)?.params ?? {} };
};

describe('partition identity routes do not shadow legacy partition keys', () => {
  test('legacy partition key "apps" remains reachable', () => {
    const result = match('/project/p/apps');
    expect(result.id).toBe('legacy-app-list');
    expect(result.params.partitionKey).toBe('apps');
  });

  test('legacy partition key "app" remains reachable', () => {
    const result = match('/project/p/app/a');
    expect(result.id).toBe('legacy-app-detail');
    expect(result.params.partitionKey).toBe('app');
    expect(result.params.appId).toBe('a');
  });

  test('identity routes remain reachable under their reserved prefix', () => {
    expect(match('/partition-identity/p/apps').id).toBe('identity-app-list');
    expect(match('/partition-identity/p/app/a').id).toBe('identity-app-detail');
  });
});
