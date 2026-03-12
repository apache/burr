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

import { Button } from '../components/common/button';
import { TwoColumnLayout } from '../components/common/layout';
import { ApplicationSummary, DefaultService } from '../api';
import { useState } from 'react';
import { useMutation, useQuery } from 'react-query';
import { Loading } from '../components/common/loading';
import { TelemetryWithSelector } from './Common';

const CounterApp = (props: { projectId: string; appId: string | undefined }) => {
  const [counterValue, setCounterValue] = useState<number>(0);

  const { isLoading } = useQuery(
    ['counter-state', props.projectId, props.appId],
    () =>
      DefaultService.getCounterStateApiV0CounterStateProjectIdAppIdGet(
        props.projectId,
        props.appId || ''
      ),
    {
      enabled: props.appId !== undefined,
      onSuccess: (data) => {
        setCounterValue(data.counter);
      }
    }
  );

  const mutation = useMutation(
    () => {
      return DefaultService.countApiV0CounterCountProjectIdAppIdPost(
        props.projectId,
        props.appId || ''
      );
    },
    {
      onSuccess: (data) => {
        setCounterValue(data.counter);
      }
    }
  );

  if (isLoading) {
    return <Loading />;
  }

  const isWaiting = mutation.isLoading;

  return (
    <div className="mr-4 bg-white w-full flex flex-col h-full">
      <h1 className="text-2xl font-bold px-4 text-gray-600">Counter Demo</h1>
      <h2 className="text-lg font-normal px-4 text-gray-500">
        A simple counter powered by Burr. Click the button to increment and watch the state machine
        on the right.
      </h2>
      <div className="flex-1 flex flex-col items-center justify-center gap-8">
        <div className="text-8xl font-bold text-gray-700">{counterValue}</div>
        <Button
          className="w-40 cursor-pointer text-lg"
          color="dark"
          disabled={isWaiting || props.appId === undefined}
          onClick={() => mutation.mutate()}
        >
          {isWaiting ? 'Counting...' : 'Count +1'}
        </Button>
        {props.appId === undefined && (
          <p className="text-gray-400 text-sm">
            Select or create a counter from the panel on the right to get started.
          </p>
        )}
      </div>
    </div>
  );
};

export const Counter = () => {
  const currentProject = 'demo_counter';
  const [currentApp, setCurrentApp] = useState<ApplicationSummary | undefined>(undefined);

  return (
    <TwoColumnLayout
      firstItem={<CounterApp projectId={currentProject} appId={currentApp?.app_id} />}
      secondItem={
        <TelemetryWithSelector
          projectId={currentProject}
          currentApp={currentApp}
          setCurrentApp={setCurrentApp}
          createNewApp={
            DefaultService.createNewApplicationApiV0CounterCreateProjectIdAppIdPost
          }
        />
      }
      mode={'third'}
    />
  );
};
