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

import { AnnotationOut, ApplicationModel, Step } from '../../../api';
import { Tabs } from '../../common/tabs';
import { DataView } from './DataView';
import { ActionView } from './ActionView';
import { GraphView } from './GraphView';
import { InsightsView } from './InsightsView';
import { ReproduceView } from './ReproduceView';
import { useContext } from 'react';
import { AppContext, SequenceLocation } from './AppView';
import { ChevronLeftIcon, ChevronRightIcon } from '@heroicons/react/24/outline';
import { AnnotationsView } from './AnnotationsView';
import { useLocationParams } from '../../../utils';

const NoStepSelected = () => {
  return (
    <div className="flex flex-col items-center justify-center h-full">
      <p className="text-xl text-gray-400">Please select a step from the table on the left</p>
    </div>
  );
};

export const AppStateView = (props: {
  steps: Step[];
  stateMachine: ApplicationModel;
  highlightedActions: Step[] | undefined;
  hoverAction: Step | undefined;
  currentActionLocation: SequenceLocation | undefined;
  graphAppId: string;
  graphPartitionKey: string | null;
  displayGraphAsTab: boolean;
  setMinimized: (minimized: boolean) => void;
  isMinimized: boolean;
  allowMinimized: boolean;
  annotations?: AnnotationOut[];
  restrictTabs?: string[];
  allowAnnotations?: boolean;
}) => {
  const { tab, setTab } = useContext(AppContext);
  const { projectId, appId, partitionKey } = useLocationParams();
  const currentStep = props.steps.find(
    (step) =>
      // We don't get the global App ID -- we assume the steps are from the right one
      step.step_start_log.sequence_id === props.currentActionLocation?.sequenceId
  );
  const priorStep =
    currentStep &&
    props.steps.find(
      (step) =>
        step.step_start_log.sequence_id === (props.currentActionLocation?.sequenceId || 0) - 1
    );

  const actionModel = props.stateMachine.actions.find(
    (action) => action.name === currentStep?.step_start_log.action
  );
  const tabs = [
    { id: 'data', displayName: 'Data' },
    { id: 'code', displayName: 'Code' },
    { id: 'reproduce', displayName: 'Reproduce' },
    { id: 'insights', displayName: 'Insights' },
    ...(props.allowAnnotations ? [{ id: 'annotations', displayName: 'Annotations' }] : [])
  ].filter((tab) => !props.restrictTabs || props.restrictTabs.includes(tab.id));
  if (
    props.displayGraphAsTab &&
    (props.restrictTabs === undefined || props.restrictTabs.includes('graph'))
  ) {
    tabs.push({ id: 'graph', displayName: 'Graph' });
  }
  const MinimizeTableIcon = props.isMinimized ? ChevronLeftIcon : ChevronRightIcon;
  return (
    <>
      <div className="flex flex-row items-center pl-4">
        {props.allowMinimized && (
          <button onClick={() => props.setMinimized(!props.isMinimized)}>
            <MinimizeTableIcon className="h-4 w-4 hover:scale-110 cursor-pointer text-gray-600" />
          </button>
        )}
        <Tabs tabs={tabs} currentTab={tab} setCurrentTab={setTab} />
      </div>
      <div className="px-4 h-full w-full hide-scrollbar overflow-y-auto">
        {tab === 'data' &&
          (currentStep ? (
            <DataView currentStep={currentStep} priorStep={priorStep} />
          ) : (
            <NoStepSelected />
          ))}
        {tab === 'code' &&
          (currentStep ? <ActionView currentAction={actionModel} /> : <NoStepSelected />)}
        {tab === 'graph' && (
          <GraphView
            stateMachine={props.stateMachine}
            currentAction={currentStep}
            highlightedActions={props.highlightedActions}
            hoverAction={props.hoverAction}
            appId={props.graphAppId}
            partitionKey={props.graphPartitionKey}
          />
        )}
        {tab === 'insights' && (
          <InsightsView
            steps={props.steps}
            appId={appId as string}
            partitionKey={partitionKey as string}
          />
        )}
        {tab === 'reproduce' &&
          (currentStep ? (
            <ReproduceView
              step={currentStep}
              appId={appId as string}
              partitionKey={partitionKey as string}
              projectID={projectId as string}
            />
          ) : (
            <NoStepSelected />
          ))}
        {tab === 'annotations' && (
          <AnnotationsView
            currentStep={currentStep}
            allSteps={props.steps}
            appId={appId as string}
            partitionKey={partitionKey === 'null' ? null : partitionKey || null}
            projectId={projectId as string}
            allAnnotations={props.annotations || []}
          />
        )}
      </div>
    </>
  );
};
