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

import type { SequenceLocation } from './AppView';

/**
 * Graph nodes are actions. An action can run many times, so a graph hover
 * cannot be stored as one sequence id. It is the action name, scoped to the
 * application that owns the graph.
 */
export type HoveredAction = {
  actionName: string;
  appId: string;
  partitionKey: string | null;
};

/**
 * A telemetry row is hovered when the pointer is on that sequence, or when
 * the pointer is on the graph node for the same action in the same application.
 */
export const isTelemetryRowHovered = (args: {
  currentHoverIndex: SequenceLocation | undefined;
  currentHoverAction: HoveredAction | undefined;
  sequenceId: number | undefined;
  actionName: string | undefined;
  appId: string;
  partitionKey: string | null;
}): boolean => {
  const sequenceMatches =
    args.sequenceId !== undefined &&
    args.currentHoverIndex?.sequenceId === args.sequenceId &&
    args.currentHoverIndex.appId === args.appId &&
    args.currentHoverIndex.partitionKey === args.partitionKey;
  const actionMatches =
    args.actionName !== undefined &&
    args.currentHoverAction?.actionName === args.actionName &&
    args.currentHoverAction.appId === args.appId &&
    args.currentHoverAction.partitionKey === args.partitionKey;
  return sequenceMatches || actionMatches;
};
