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

import { useQuery } from 'react-query';
import { Navigate, useParams } from 'react-router';
import { Loading } from '../common/loading';
import { ApplicationSummary, DefaultService } from '../../api';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '../common/table';
import { DateTimeDisplay } from '../common/dates';
import { useEffect, useState } from 'react';
import { FunnelIcon, MinusIcon, PlusIcon } from '@heroicons/react/24/outline';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { MdForkRight } from 'react-icons/md';
import { RiCornerDownRightLine } from 'react-icons/ri';
import React from 'react';
import { Paginator } from '../common/pagination';
import {
  applicationIdentityKey,
  appDetailPath,
  appListPath,
  decodeLegacyAppListPartitionSegment,
  partitionIdentityTag,
  partitionQueryArgs
} from '../../partitionIdentity';

const StepCountHeader = (props: {
  displayZeroCount: boolean;
  setDisplayZeroCount: (displayZeroCount: boolean) => void;
}) => {
  const fillColor = props.displayZeroCount ? 'fill-gray-300' : 'fill-gray-700';
  const borderColor = props.displayZeroCount ? 'text-gray-300' : 'text-gray-700';
  return (
    <div className="flex flex-row items-center gap-1">
      <FunnelIcon
        className={`h-5 w-5 hover:scale-125 cursor-pointer ${fillColor} ${borderColor}`}
        onClick={() => {
          props.setDisplayZeroCount(!props.displayZeroCount);
        }}
      />
      <span>Seq ID</span>
    </div>
  );
};

const isNullPartitionKey = (partitionKey: string | null) => partitionKey === null;

const getForkID = (app: ApplicationSummary) => {
  if (app.parent_pointer) {
    return app.parent_pointer.app_id;
  } else {
    return null;
  }
};

const getParentPartitionKey = (app: ApplicationSummary) => {
  if (app.parent_pointer) {
    return app.parent_pointer.partition_key;
  } else {
    return null;
  }
};

const parentIdentityKey = (app: ApplicationSummary): string => {
  const pointer = app.spawning_parent_pointer;
  return pointer ? `${pointer.app_id}\u0000${partitionIdentityTag(pointer.partition_key)}` : '';
};

/**
 * Sub-application list -- handles spaned applications.
 * This contains a list of applications that correspond to a parent application.
 * It is either an individual application or more when recursively applied
 * @param props
 * @returns
 */
const AppSubList = (props: {
  app: ApplicationSummary;
  navigate: (url: string) => void;
  projectId: string;
  spawningParentMap: Map<string, ApplicationSummary[]>;
  parentHovered?: boolean;
  depth?: number;
  displayPartitionKey: boolean;
}) => {
  const [subAppsExpanded, setSubAppsExpanded] = useState(false);

  const forkID = getForkID(props.app);
  const { app } = props;
  const ExpandIcon = subAppsExpanded ? MinusIcon : PlusIcon;

  const [isHovered, setIsHovered] = useState(true);
  const isHighlighted = props.parentHovered || isHovered;
  const depth = props.depth || 0;
  return (
    <>
      <TableRow
        onMouseEnter={() => {
          setIsHovered(true);
        }}
        onMouseLeave={() => {
          setIsHovered(false);
        }}
        key={applicationIdentityKey(props.app.app_id, props.app.partition_key)}
        className={`cursor-pointer ${isHighlighted ? 'bg-gray-50' : ''}`}
        onClick={() => {
          props.navigate(appDetailPath(props.projectId, app.app_id, app.partition_key));
        }}
      >
        {props.displayPartitionKey && (
          <TableCell className="text-gray-600 font-sans">
            {isNullPartitionKey(app.partition_key) ? (
              <></>
            ) : (
              <Link
                to={appListPath(props.projectId, app.partition_key)}
                className="hover:underline"
                onClick={(e) => {
                  props.navigate(appListPath(props.projectId, app.partition_key));
                  e.stopPropagation();
                }}
              >
                {app.partition_key}
              </Link>
            )}
          </TableCell>
        )}
        <TableCell className="font-semibold text-gray-700">
          <div className="flex flex-row gap-1 items-center md:min-w-[21rem] md:max-w-none max-w-24">
            {[...Array(depth).keys()].map((i) => (
              <RiCornerDownRightLine
                key={i}
                className={`${i === depth - 1 ? 'opacity-100' : 'opacity-0'} text-lg text-gray-600`}
              ></RiCornerDownRightLine>
            ))}
            {app.app_id}
          </div>
        </TableCell>
        <TableCell>
          <DateTimeDisplay date={app.last_written} mode="long" />
        </TableCell>
        <TableCell className="z-50">
          {forkID ? (
            <MdForkRight
              className=" hover:scale-125 h-5 w-5 text-gray-600 "
              onClick={(e) => {
                props.navigate(appDetailPath(props.projectId, forkID, getParentPartitionKey(app)));
                e.stopPropagation();
              }}
            />
          ) : (
            <></>
          )}
        </TableCell>
        <TableCell>
          {props.spawningParentMap.has(
            applicationIdentityKey(props.app.app_id, props.app.partition_key)
          ) ? (
            <div className="flex flex-row items-center gap-1">
              <ExpandIcon
                className="h-4 w-4 text-gray-600 hover:scale-110 cursor-pointer"
                onClick={(e) => {
                  setSubAppsExpanded(!subAppsExpanded);
                  e.stopPropagation();
                }}
              />
              <span className="text-gray-600">
                (
                {
                  props.spawningParentMap.get(
                    applicationIdentityKey(props.app.app_id, props.app.partition_key)
                  )?.length
                }
                )
              </span>
            </div>
          ) : (
            <></>
          )}
        </TableCell>
        <TableCell className="text-gray-600">{app.num_steps}</TableCell>
      </TableRow>
      {props.spawningParentMap.has(
        applicationIdentityKey(props.app.app_id, props.app.partition_key)
      ) && subAppsExpanded
        ? props.spawningParentMap
            .get(applicationIdentityKey(props.app.app_id, props.app.partition_key))
            ?.map((subApp) => {
              return (
                <AppSubList
                  key={applicationIdentityKey(subApp.app_id, subApp.partition_key)}
                  displayPartitionKey={props.displayPartitionKey}
                  app={subApp}
                  navigate={props.navigate}
                  projectId={props.projectId}
                  spawningParentMap={props.spawningParentMap}
                  parentHovered={isHighlighted}
                  depth={depth + 1}
                />
              );
            })
        : null}
    </>
  );
};
/**
 * List of applications. Purely rendering a list, also sorts them.
 */
export const AppListTable = (props: { apps: ApplicationSummary[]; projectId: string }) => {
  const appsCopy = [...props.apps];
  const [displayZeroCount, setDisplayZeroCount] = useState(true);
  const navigate = useNavigate();
  const appsToDisplay = appsCopy
    .sort((a, b) => {
      return new Date(a.last_written) > new Date(b.last_written) ? -1 : 1;
    })
    .filter((app) => {
      return app.num_steps > 0 || displayZeroCount;
    });

  // Maps from parents -> children
  const spawningParentMap = appsToDisplay.reduce((acc, app) => {
    if (app.spawning_parent_pointer) {
      const key = parentIdentityKey(app);
      if (acc.has(key)) {
        acc.get(key)!.push(app);
      } else {
        acc.set(key, [app]);
      }
    }
    return acc;
  }, new Map<string, ApplicationSummary[]>());

  // Display the parents no matter what
  // const rootAppsToDisplay = appsToDisplay.filter((app) => app.spawning_parent_pointer === null);
  const rootAppsToDisplay = appsToDisplay;
  const anyHavePartitionKey = rootAppsToDisplay.some(
    (app) => !isNullPartitionKey(app.partition_key)
  );

  const tableRef = React.createRef<HTMLDivElement>();
  const [tableHeight, setTableHeight] = useState('auto');

  const updateTableHeight = () => {
    if (tableRef.current) {
      const parentElement = tableRef.current.parentElement;
      if (parentElement) {
        const parentHeight = parentElement.clientHeight;
        const tableTop =
          tableRef.current.getBoundingClientRect().top - parentElement.getBoundingClientRect().top;
        const availableHeight = parentHeight - tableTop;
        setTableHeight(`${availableHeight}px`);
      }
    }
  };

  useEffect(() => {
    updateTableHeight(); // Initial calculation on mount
    window.addEventListener('resize', updateTableHeight); // Recalculate on window resize

    // Set up a ResizeObserver to listen to changes in the parent element's size
    const observer = new ResizeObserver(updateTableHeight);
    if (tableRef.current?.parentElement) {
      observer.observe(tableRef.current.parentElement);
    }

    return () => {
      window.removeEventListener('resize', updateTableHeight);
      observer.disconnect(); // Cleanup observer on unmount
    };
  }, []);

  return (
    <div ref={tableRef} style={{ height: tableHeight }} className="flex flex-col justify-between">
      <Table dense={1} style={{ maxHeight: tableHeight }} className="hide-scrollbar">
        <TableHead className=" bg-white sticky top-0 z-50">
          <TableRow>
            {anyHavePartitionKey && <TableHeader>Partition Key</TableHeader>}
            <TableHeader>ID</TableHeader>
            <TableHeader>Last Run</TableHeader>
            <TableHeader>Forked</TableHeader>
            <TableHeader>Sub Apps</TableHeader>
            <TableHeader>
              <StepCountHeader
                displayZeroCount={displayZeroCount}
                setDisplayZeroCount={setDisplayZeroCount}
              />
            </TableHeader>
          </TableRow>
        </TableHead>
        <TableBody>
          {appsToDisplay.map((app) => {
            return (
              <AppSubList
                key={applicationIdentityKey(app.app_id, app.partition_key)}
                app={app}
                projectId={props.projectId}
                navigate={navigate}
                spawningParentMap={spawningParentMap}
                displayPartitionKey={anyHavePartitionKey}
              />
            );
          })}
        </TableBody>
      </Table>
    </div>
  );
};

const DEFAULT_LIMIT = 100;

/**
 * List of applications. This fetches data from the BE and passes it to the table
 */
export const AppList = () => {
  const { projectId, partitionKey } = useParams();
  const [searchParams] = useSearchParams();
  const currentOffset = searchParams.get('offset') ? parseInt(searchParams.get('offset')!) : 0;
  const pageSize = DEFAULT_LIMIT;
  const nonePartition = searchParams.get('none_partition') === 'true';
  const identity: string | null | undefined = searchParams.has('partition_key')
    ? (searchParams.get('partition_key') as string)
    : nonePartition
      ? null
      : decodeLegacyAppListPartitionSegment(partitionKey);
  const queryArgs = identity === undefined ? {} : partitionQueryArgs(identity);
  const { data, error } = useQuery(
    ['apps', projectId, identity, pageSize, currentOffset],
    () =>
      DefaultService.listAppsByPartitionQuery(
        projectId as string,
        queryArgs.partitionKey,
        queryArgs.nonePartition,
        pageSize,
        currentOffset
      ),
    { enabled: projectId !== undefined }
  );

  const [queriedData, setQueriedData] = useState(data);

  useEffect(() => {
    if (data !== undefined) {
      setQueriedData(data);
    }
  }, [data]);

  if (projectId === undefined) {
    return <Navigate to={'/projects'} />;
  }

  if (error) return <div>Error loading apps</div>;
  const shouldDisplayPagination = queriedData ? queriedData.total > pageSize : false;
  return (
    <div className="h-full flex flex-col gap-1 justify-between">
      {queriedData !== undefined ? (
        <AppListTable apps={queriedData.applications} projectId={projectId} />
      ) : (
        <Loading />
      )}
      <div className="flex flex-row w-full justify-center">
        {shouldDisplayPagination && (
          <Paginator
            currentPage={currentOffset / pageSize + 1}
            getPageURL={(page) => {
              const base = appListPath(projectId as string, identity);
              return `${base}${base.includes('?') ? '&' : '?'}offset=${(page - 1) * pageSize}`;
            }}
            totalPages={queriedData ? Math.ceil(queriedData?.total / pageSize) : undefined}
            // TODO -- add query result back
            hasNextPage={queriedData ? currentOffset + pageSize < queriedData.total : false}
          ></Paginator>
        )}
      </div>
    </div>
  );
};
