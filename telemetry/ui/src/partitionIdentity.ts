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

/** A partition identity is either the None partition or an exact string. */
export type PartitionIdentity = string | null;

/** Tag used to keep null, "", "null" and "__none__" distinct in composite keys. */
export const partitionIdentityTag = (partitionKey: PartitionIdentity): string =>
  partitionKey === null ? 'none' : `string:${partitionKey}`;

/** Composite React key for an application instance. */
export const applicationIdentityKey = (appId: string, partitionKey: PartitionIdentity): string =>
  `${appId}\u0000${partitionIdentityTag(partitionKey)}`;

/** Query arguments for the unambiguous partition-aware API endpoints. */
export const partitionQueryArgs = (
  partitionKey: PartitionIdentity
): { partitionKey?: string; nonePartition?: boolean } =>
  partitionKey === null ? { nonePartition: true } : { partitionKey };

/** Query string for identity-preserving frontend navigation. */
export const partitionSearch = (partitionKey: PartitionIdentity): string =>
  partitionKey === null
    ? '?none_partition=true'
    : `?partition_key=${encodeURIComponent(partitionKey)}`;

/** URL for an application detail page that preserves its partition identity. */
export const appDetailPath = (
  projectId: string,
  appId: string,
  partitionKey: PartitionIdentity
): string =>
  `/partition-identity/${encodeURIComponent(projectId)}/app/${encodeURIComponent(appId)}${partitionSearch(partitionKey)}`;

/** URL for an application list page filtered by an exact partition identity. */
export const appListPath = (projectId: string, partitionKey?: PartitionIdentity): string =>
  `/partition-identity/${encodeURIComponent(projectId)}/apps${
    partitionKey === undefined ? '' : partitionSearch(partitionKey)
  }`;

/** Decode the legacy AppList path segment exactly as main did. */
export const decodeLegacyAppListPartitionSegment = (
  segment: string | undefined
): PartitionIdentity | undefined => {
  if (segment === undefined) return undefined;
  if (segment === '__none__') return undefined; // historical "no filter" route
  return segment; // including the literal string "null"
};

/** Decode the legacy path segment into an identity, if it is unambiguous. */
export const decodeLegacyPartitionSegment = (
  segment: string | undefined
): PartitionIdentity | undefined => {
  if (segment === undefined) return undefined;
  if (segment === 'null') return null;
  if (segment === '__none__') return undefined; // historical "no filter" route
  return segment;
};
