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

import { KeyboardEvent, useState } from 'react';
import { ApplicationSummary, DefaultService, ResearchSummary } from '../api';
import { TwoColumnLayout } from '../components/common/layout';
import { TelemetryWithSelector } from './Common';
import { Button } from '../components/common/button';
import { useMutation, useQuery } from '@tanstack/react-query';
import { Text } from '../components/common/text';
import { Field, Label } from '../components/common/fieldset';

const DEFAULT_RESEARCH_SUMMARY: ResearchSummary = {
  running_summary: ''
};

export const ResearchSummaryView = (props: { summary: string }) => {
  return (
    <>
      <Text>
        <pre className="whitespace-pre-wrap text-xs">{props.summary}</pre>
      </Text>
    </>
  );
};

export const DeepResearcher = (props: { projectId: string; appId: string | undefined }) => {
  const [currentTopic, setCurrentTopic] = useState<string>('');
  const [displayedReport, setDisplayedReport] = useState(DEFAULT_RESEARCH_SUMMARY);
  const { data: validationData, isLoading: isValidationLoading } = useQuery({
    queryKey: ['valid'],
    queryFn: DefaultService.validateEnvironmentApiV0DeepResearcherValidateGet
  });

  const mutation = useMutation({
    mutationFn: (topic: string) => {
      return DefaultService.researchResponseApiV0DeepResearcherResponseProjectIdAppIdPost(
        props.projectId,
        props.appId || '',
        topic
      );
    },
    onSuccess: (data) => {
      setDisplayedReport(data);
    }
  });
  const sendTopic = () => {
    if (currentTopic !== '') {
      mutation.mutate(currentTopic);
      setCurrentTopic('');
      setDisplayedReport(DEFAULT_RESEARCH_SUMMARY);
    }
  };
  const isResearcherWaiting = mutation.isPending || isValidationLoading;
  const displayValidationError = validationData !== null;

  return (
    <div className="px-4 bg-white  w-full flex flex-col  h-full gap-5 overflow-y-scroll">
      <h1 className="text-2xl font-bold text-gray-600">{'Learn Burr '}</h1>
      <h2 className="text-lg font-normal text-gray-500 flex flex-row">
        The research assistant below is implemented using Burr. Watch the Burr UI (on the right)
        change as you chat...
      </h2>
      <div className="flex flex-col">
        {displayValidationError && (
          <p className="text-lg font-normal text-dwred">{validationData}</p>
        )}
        {!displayValidationError && (
          <Field>
            <Label className="text-lg font-bold text-gray-600">Report</Label>
          </Field>
        )}
        <ResearchSummaryView summary={displayedReport.running_summary} />
      </div>
      <div className="flex items-center pt-4 gap-2">
        <input
          className="flex h-10 w-full rounded-md border border-[#e5e7eb] px-3 py-2 text-sm placeholder-[#6b7280] focus:outline-none focus:ring-2 focus:ring-[#9ca3af] disabled:cursor-not-allowed disabled:opacity-50 text-[#030712] focus-visible:ring-offset-2"
          placeholder="how to get a job in data science"
          value={currentTopic}
          onChange={(e) => setCurrentTopic(e.target.value)}
          onKeyDown={(e: KeyboardEvent<HTMLInputElement>) => {
            if (e.key === 'Enter' && !e.shiftKey) {
              e.preventDefault();
              sendTopic();
            }
          }}
          disabled={isResearcherWaiting || props.appId === undefined || displayValidationError}
        />
        <Button
          className="w-min cursor-pointer h-full"
          color="dark"
          disabled={isResearcherWaiting || props.appId === undefined || displayValidationError}
          onClick={() => {
            sendTopic();
          }}
        >
          Send
        </Button>
      </div>
    </div>
  );
};

export const DeepResearcherWithTelemetry = () => {
  const currentProject = 'demo_deep_researcher';
  const [currentApp, setCurrentApp] = useState<ApplicationSummary | undefined>(undefined);
  return (
    <TwoColumnLayout
      firstItem={<DeepResearcher projectId={currentProject} appId={currentApp?.app_id} />}
      secondItem={
        <TelemetryWithSelector
          projectId={currentProject}
          currentApp={currentApp}
          setCurrentApp={setCurrentApp}
          createNewApp={
            DefaultService.createNewApplicationApiV0DeepResearcherCreateProjectIdAppIdPost
          }
        />
      }
      mode={'third'}
    ></TwoColumnLayout>
  );
};
