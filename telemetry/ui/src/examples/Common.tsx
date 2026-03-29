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

import { useMutation, useQuery } from '@tanstack/react-query';
import { ApplicationSummary } from '../api/models/ApplicationSummary';
import { DateTimeDisplay } from '../components/common/dates';
import { MiniTelemetry } from './MiniTelemetry';
import { DefaultService } from '../api';
import AsyncCreatableSelect from 'react-select/async-creatable';

type CreateNewApp = typeof DefaultService.createNewApplicationApiV0ChatbotCreateProjectIdAppIdPost;

export const TelemetryWithSelector = (props: {
  projectId: string;
  currentApp: ApplicationSummary | undefined;
  setCurrentApp: (app: ApplicationSummary) => void;
  createNewApp: CreateNewApp;
}) => {
  return (
    <div className="w-full h-[90%]">
      <div className="w-full">
        <ChatbotAppSelector
          projectId={props.projectId}
          setApp={props.setCurrentApp}
          currentApp={props.currentApp}
          placeholder={'Select a conversation or create a new one by typing...'}
          createNewApp={props.createNewApp}
        />
      </div>
      <MiniTelemetry
        projectId={props.projectId}
        appId={props.currentApp?.app_id}
        partitionKey={null}
      ></MiniTelemetry>
    </div>
  );
};

const Label = (props: { application: ApplicationSummary }) => {
  return (
    <div className="flex flex-row gap-2 items-center justify-between">
      <div className="flex flex-row gap-2 items-center">
        <span className="text-gray-400 w-10">{props.application.num_steps}</span>
        <span>{props.application.app_id}</span>
      </div>
      <DateTimeDisplay date={props.application.first_written} mode="short" />
    </div>
  );
};

export const ChatbotAppSelector = (props: {
  projectId: string;
  setApp: (app: ApplicationSummary) => void;
  currentApp: ApplicationSummary | undefined;
  placeholder: string;
  createNewApp: CreateNewApp;
}) => {
  const { projectId, setApp } = props;
  const { data, refetch } = useQuery({
    queryKey: ['apps', projectId],
    // TODO - use the right partition key
    queryFn: () =>
      DefaultService.getAppsApiV0ProjectIdPartitionKeyAppsGet(projectId as string, '__none__'),
    enabled: projectId !== undefined
  });
  const createAndUpdateMutation = useMutation({
    mutationFn: (app_id: string) => props.createNewApp(projectId, app_id),
    onSuccess: (appID) => {
      refetch().then((data) => {
        const appSummaries = data.data?.applications || [];
        const app = appSummaries.find((app) => app.app_id === appID);
        if (app) {
          setApp(app);
        }
      });
    }
  });
  const appSummaries = data?.applications || [];
  const appSetter = (appID: string) => createAndUpdateMutation.mutate(appID);
  const dataOrEmpty = Array.from(appSummaries || []);
  const options = dataOrEmpty
    .sort((a, b) => {
      return new Date(a.last_written) > new Date(b.last_written) ? -1 : 1;
    })
    .map((app) => {
      return {
        value: app.app_id,
        label: <Label application={app} />
      };
    });
  return (
    <AsyncCreatableSelect
      placeholder={props.placeholder}
      cacheOptions
      defaultOptions={options}
      options={options}
      onCreateOption={appSetter}
      value={options.find((option) => option.value === props.currentApp?.app_id) || null}
      onChange={(choice) => {
        const app = dataOrEmpty.find((app) => app.app_id === choice?.value);
        if (app) {
          setApp(app);
        }
      }}
      loadOptions={(inputValue: string) => {
        return Promise.resolve(
          options.filter((option) => {
            return option.value.startsWith(inputValue);
          })
        );
      }}
    />
  );
};
