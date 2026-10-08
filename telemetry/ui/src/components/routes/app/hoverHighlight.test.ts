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

import { expect, test } from 'vitest';
import { isTelemetryRowHovered } from './hoverHighlight';

const appId = 'app-1';
const partitionKey = 'partition-1';

const sequenceHover = {
  appId,
  partitionKey,
  sequenceId: 3
};

const actionHover = {
  actionName: 'respond',
  appId,
  partitionKey
};

const row = {
  sequenceId: 7,
  actionName: 'respond',
  appId,
  partitionKey
};

test('sequence hover highlights only that sequence in the same application', () => {
  expect(
    isTelemetryRowHovered({
      currentHoverIndex: sequenceHover,
      currentHoverAction: undefined,
      ...row,
      sequenceId: 3
    })
  ).toBe(true);
  expect(
    isTelemetryRowHovered({
      currentHoverIndex: sequenceHover,
      currentHoverAction: undefined,
      ...row,
      sequenceId: 4
    })
  ).toBe(false);
  expect(
    isTelemetryRowHovered({
      currentHoverIndex: sequenceHover,
      currentHoverAction: undefined,
      ...row,
      sequenceId: 3,
      appId: 'other-app'
    })
  ).toBe(false);
});

test('graph action hover highlights every run of that action', () => {
  expect(
    isTelemetryRowHovered({
      currentHoverIndex: undefined,
      currentHoverAction: actionHover,
      ...row,
      sequenceId: 1
    })
  ).toBe(true);
  expect(
    isTelemetryRowHovered({
      currentHoverIndex: undefined,
      currentHoverAction: actionHover,
      ...row,
      sequenceId: 9
    })
  ).toBe(true);
  expect(
    isTelemetryRowHovered({
      currentHoverIndex: undefined,
      currentHoverAction: actionHover,
      ...row,
      actionName: 'retrieve'
    })
  ).toBe(false);
});

test('graph action hover does not cross applications or partitions', () => {
  expect(
    isTelemetryRowHovered({
      currentHoverIndex: undefined,
      currentHoverAction: actionHover,
      ...row,
      appId: 'other-app'
    })
  ).toBe(false);
  expect(
    isTelemetryRowHovered({
      currentHoverIndex: undefined,
      currentHoverAction: actionHover,
      ...row,
      partitionKey: null
    })
  ).toBe(false);
  expect(
    isTelemetryRowHovered({
      currentHoverIndex: undefined,
      currentHoverAction: { ...actionHover, partitionKey: null },
      ...row,
      partitionKey: null
    })
  ).toBe(true);
});

test('either hover source is enough, and neither leaves the row idle', () => {
  expect(
    isTelemetryRowHovered({
      currentHoverIndex: sequenceHover,
      currentHoverAction: { ...actionHover, actionName: 'other' },
      ...row,
      sequenceId: 3
    })
  ).toBe(true);
  expect(
    isTelemetryRowHovered({
      currentHoverIndex: undefined,
      currentHoverAction: undefined,
      ...row
    })
  ).toBe(false);
  expect(
    isTelemetryRowHovered({
      currentHoverIndex: undefined,
      currentHoverAction: actionHover,
      ...row,
      sequenceId: undefined,
      actionName: undefined
    })
  ).toBe(false);
});
