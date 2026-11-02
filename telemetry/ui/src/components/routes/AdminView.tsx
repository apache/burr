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
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '../common/table';
import { DefaultService } from '../../api';
import { Loading } from '../common/loading';
import { DateTimeDisplay, DurationDisplay } from '../common/dates';
import JsonView from '@uiw/react-json-view';
import { useState } from 'react';
import { FunnelIcon } from '@heroicons/react/24/outline';

const RecordsHeader = (props: {
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
      <span>Records Processed</span>
    </div>
  );
};

/**
 * Currently just shows indexing jobs, but we'll likely
 * want to add more depending on whether the backend supports it.
 * @returns A rendered admin view object
 */
export const AdminView = () => {
  const [displayZeroCount, setDisplayZeroCount] = useState(false);

  const { data, isLoading } = useQuery({
    queryKey: ['indexingJobs', displayZeroCount],
    queryFn: () =>
      DefaultService.getIndexingJobsApiV0IndexingJobsGet(
        0, // TODO -- add pagination
        100,
        !displayZeroCount
      )
  });
  if (isLoading) {
    return <Loading />;
  }

  return (
    <Table dense={1}>
      <TableHead>
        <TableRow>
          <TableHeader>ID</TableHeader>
          <TableHeader>Start Time</TableHeader>
          <TableHeader>Duration</TableHeader>
          <TableHeader>Status</TableHeader>
          <TableHeader>
            <RecordsHeader
              displayZeroCount={displayZeroCount}
              setDisplayZeroCount={setDisplayZeroCount}
            />
          </TableHeader>
          <TableHeader>Metadata</TableHeader>
        </TableRow>
      </TableHead>
      <TableBody>
        {data?.map((job) => {
          return (
            <TableRow key={job.id} className="hover:bg-gray-50">
              <TableCell>{job.id}</TableCell>
              <TableCell>
                {<DateTimeDisplay date={job.start_time} mode={'short'}></DateTimeDisplay>}
              </TableCell>
              <TableCell>
                {job.end_time ? (
                  <DurationDisplay
                    startDate={job.start_time}
                    endDate={job.end_time}
                  ></DurationDisplay>
                ) : (
                  <></>
                )}
              </TableCell>
              <TableCell>{job.status.toLowerCase()}</TableCell>
              <TableCell>{job.records_processed}</TableCell>
              <TableCell>
                <JsonView value={job.metadata} displayDataTypes enableClipboard={false}></JsonView>
              </TableCell>
            </TableRow>
          );
        })}
      </TableBody>
    </Table>
  );
};
