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

import { ActionModel, TransitionModel } from '../api';

/**
 * Returns action names whose writes[] intersect with the given action's reads[].
 * These are the upstream nodes that produce state keys this action consumes.
 */
export const getUpstreamWriters = (
  actionName: string,
  actions: ActionModel[],
  _transitions: TransitionModel[]
): string[] => {
  const target = actions.find((a) => a.name === actionName);
  if (!target || !target.reads || target.reads.length === 0) return [];

  const readsSet = new Set(target.reads);
  return actions
    .filter((a) => a.name !== actionName && (a.writes || []).some((w) => readsSet.has(w)))
    .map((a) => a.name);
};

/**
 * Returns action names whose reads[] intersect with the given action's writes[].
 * These are the downstream nodes that consume state keys this action produces.
 */
export const getDownstreamReaders = (
  actionName: string,
  actions: ActionModel[],
  _transitions: TransitionModel[]
): string[] => {
  const target = actions.find((a) => a.name === actionName);
  if (!target || !target.writes || target.writes.length === 0) return [];

  const writesSet = new Set(target.writes);
  return actions
    .filter((a) => a.name !== actionName && (a.reads || []).some((r) => writesSet.has(r)))
    .map((a) => a.name);
};

/**
 * Returns a map of action name to unresolved read keys.
 * A read is "unresolved" if no other action in the graph writes that key.
 */
export const getUnresolvedReads = (
  actions: ActionModel[],
  _transitions: TransitionModel[]
): Map<string, string[]> => {
  const allWrites = new Set(actions.flatMap((a) => a.writes || []));
  const result = new Map<string, string[]>();

  for (const action of actions) {
    const reads = action.reads || [];
    const unresolved = reads.filter((r) => !allWrites.has(r));
    if (unresolved.length > 0) {
      result.set(action.name, unresolved);
    }
  }

  return result;
};
