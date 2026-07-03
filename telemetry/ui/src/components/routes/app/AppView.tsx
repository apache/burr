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

import { Navigate } from 'react-router';
import {
  AnnotationCreate,
  AnnotationOut,
  AnnotationUpdate,
  AttributeModel,
  DefaultService
} from '../../../api';
import { useMutation, useQuery } from 'react-query';
import { Loading } from '../../common/loading';
import { ApplicationTable } from './StepList';
import { TwoColumnLayout, TwoRowLayout } from '../../common/layout';
import { AppStateView } from './StateMachine';
import { createContext, useEffect, useState } from 'react';
import { Status, useLocationParams } from '../../../utils';
import { GraphView } from './GraphView';
import { useSearchParams } from 'react-router-dom';

export const REFRESH_INTERVAL = 500;

export const backgroundColorsForStatus = (status: Status) => {
  const colorsByStatus = {
    success: 'bg-green-500/80',
    failure: 'bg-dwred/80',
    running: 'bg-dwlightblue/80'
  };
  return colorsByStatus[status];
};

/**
 * Some tailwind mappings for bg colors -- we get progressively lighter the further back in
 * time we go
 * @param index Index away from the current step
 * @param status Status of the step at that index
 * @returns A tailwind class for the background color
 */
export const backgroundColorsForIndex = (index: number, status: Status) => {
  const colorsByStatus = {
    success: [
      'bg-green-500/80',
      'bg-green-500/70',
      'bg-green-500/60',
      'bg-green-500/50',
      'bg-green-500/30',
      'bg-green-500/10',
      'bg-green-500/5'
    ],
    failure: [
      'bg-dwred/80',
      'bg-dwred/70',
      'bg-dwred/60',
      'bg-dwred/50',
      'bg-dwred/30',
      'bg-dwred/10',
      'bg-dwred/5'
    ],
    // We likely will not need the prior running colors but :shrug: best to keep it consistent
    running: [
      'bg-dwlightblue/80',
      'bg-dwlightblue/70',
      'bg-dwlightblue/60',
      'bg-dwlightblue/50',
      'bg-dwlightblue/30',
      'bg-dwlightblue/10',
      'bg-dwlightblue/5'
    ]
  };
  const colors = colorsByStatus[status];
  if (index < colors.length) {
    return colors[index];
  }
  return colors[colors.length - 1];
};

// Default number of previous actions to show
const NUM_PREVIOUS_ACTIONS = 0;

export type SequenceLocation = {
  appId: string;
  partitionKey: string | null;
  sequenceId: number;
};

export type AnnotationEditingContext = SequenceLocation & {
  spanId: string | null;
  attributeName?: string;
  existingAnnotation: AnnotationOut | undefined;
};

// TODO -- break this out into multiple pieces -- it's a bit of a monolith of data passed down
// Classic react problem of using context when data should be wired through -- it inherently gets super complicated...
export type HighlightState = {
  attributesHighlighted: AttributeModel[];
  setAttributesHighlighted: (attributes: AttributeModel[]) => void;
  setTab: (tab: string) => void;
  tab: string;
  setCurrentSelectedIndex: (index: SequenceLocation | undefined) => void;
  currentSelectedIndex?: SequenceLocation;
  setCurrentHoverIndex: (index: SequenceLocation | undefined) => void;
  currentHoverIndex?: SequenceLocation;
  currentEditingAnnotationContext?: AnnotationEditingContext;
  setCurrentEditingAnnotationContext: (
    annotationContext: AnnotationEditingContext | undefined
  ) => void;
  createAnnotation: (
    projectId: string,
    partitionKey: string | null,
    appId: string,
    sequenceId: number,
    spanId: string | undefined,
    annotation: AnnotationCreate
  ) => Promise<AnnotationOut>;
  updateAnnotation: (
    annotationID: number,
    annotationUpdate: AnnotationUpdate
  ) => Promise<AnnotationOut>;
  refreshAnnotationData: () => void;
};

export const AppContext = createContext<HighlightState>({
  attributesHighlighted: [],
  setAttributesHighlighted: () => {},
  setTab: () => {},
  tab: 'data',
  setCurrentSelectedIndex: () => {},
  currentSelectedIndex: undefined,
  setCurrentHoverIndex: () => {},
  currentHoverIndex: undefined,
  currentEditingAnnotationContext: undefined,
  setCurrentEditingAnnotationContext: () => {},
  createAnnotation: () => {
    throw new Error('Not to be used with default context values');
  },
  updateAnnotation: () => {
    throw new Error('Not to be used with default context values');
  },
  refreshAnnotationData: () => {}
});

/**
 * View for the "Application" page. This has two columns:
 * 1. A list of steps
 * 2. A view of the state machine/data/action
 */
export const AppView = (props: {
  projectId: string;
  appId: string;
  partitionKey: string | null;
  orientation: 'stacked_vertical' | 'stacked_horizontal';
  defaultAutoRefresh?: boolean;
  enableFullScreenStepView: boolean;
  enableMinimizedStepView: boolean;
  allowAnnotations: boolean;
  restrictTabs?: string[];
  disableNavigateSteps?: boolean;
  forceCurrentActionIndex?: SequenceLocation;
  forceFullScreen?: boolean;
}) => {
  const [searchParams, setSearchParams] = useSearchParams();
  const [topToBottomChronological, setTopToBottomChronological] = useState(true);
  const [inspectViewOpen, setInspectViewOpen] = useState(false);

  const currentSequenceLocation = (
    searchParams.get('sequence_location')
      ? JSON.parse(searchParams.get('sequence_location')!)
      : undefined
  ) as SequenceLocation | undefined;

  // we want to use the current App ID passed in
  const appID = props.appId;
  // But if we want to focus on sub-applications we need to load those steps as well
  // These will get passed to the data views
  const currentFocusAppID =
    currentSequenceLocation?.appId !== undefined ? currentSequenceLocation?.appId : appID;
  // Ditto with partition key
  const partitionKey = props.partitionKey;
  const currentFocusPartitionKey =
    currentSequenceLocation?.partitionKey !== undefined
      ? currentSequenceLocation?.partitionKey
      : props.partitionKey;
  const _setCurrentSequenceLocation = (location: SequenceLocation | undefined) => {
    const newSearchParams = new URLSearchParams(searchParams); // Clone the searchParams
    if (location !== undefined) {
      newSearchParams.set('sequence_location', JSON.stringify(location));
    } else {
      newSearchParams.delete('sequence_location');
    }
    setSearchParams(newSearchParams); // Update the searchParams with the new object
  };

  if (
    props.forceCurrentActionIndex !== undefined &&
    JSON.stringify(currentSequenceLocation) !== JSON.stringify(props.forceCurrentActionIndex)
  ) {
    _setCurrentSequenceLocation(props.forceCurrentActionIndex);
  }

  const setCurrentSequenceLocation = (location: SequenceLocation | undefined) => {
    if (!props.disableNavigateSteps) {
      _setCurrentSequenceLocation(location);
    }
  };
  const { projectId } = props;
  // const [currentActionIndex, setCurrentActionIndex] = useState<number | undefined>(undefined);
  const [hoverIndex, setHoverIndex] = useState<SequenceLocation | undefined>(undefined);
  const [autoRefresh, setAutoRefresh] = useState(props.defaultAutoRefresh || false);
  const shouldQuery = projectId !== undefined && appID !== undefined;
  const [minimizedTable, setMinimizedTable] = useState(false);
  const [highlightedAttributes, setHighlightedAttributes] = useState<AttributeModel[]>([]);
  const fullScreen =
    props.forceFullScreen ||
    (searchParams.get('full') === 'true' && props.enableFullScreenStepView);
  const displayGraphAsTabs = props.orientation === 'stacked_vertical' || fullScreen;
  const defaultTab = displayGraphAsTabs ? 'graph' : 'data';
  // const [currentTab, setCurrentTab] = useState(defaultTab);
  const currentTab = searchParams.get('tab') || defaultTab;
  const setCurrentTab = (tab: string) => {
    const newSearchParams = new URLSearchParams(searchParams); // Clone the searchParams
    newSearchParams.set('tab', tab);
    setSearchParams(newSearchParams); // Update the searchParams with the new object
  };
  const setFullScreen = (full: boolean) => {
    const newSearchParams = new URLSearchParams(searchParams); // Clone the searchParams
    if (full) {
      newSearchParams.set('full', 'true');
    } else {
      newSearchParams.delete('full');
    }
    setSearchParams(newSearchParams); // Update the searchParams with the new object
  };
  const [currentEditingAnnotationContext, setCurrentEditingAnnotationContext] = useState<
    AnnotationEditingContext | undefined
  >(undefined);
  const { data: backendSpec } = useQuery(['backendSpec'], () =>
    DefaultService.getAppSpecApiV0MetadataAppSpecGet().then((response) => {
      return response;
    })
  );
  const { data, error } = useQuery(
    ['steps', appID, partitionKey],
    () =>
      DefaultService.getApplicationLogsApiV0ProjectIdAppIdPartitionKeyAppsGet(
        projectId as string,
        appID as string,
        props.partitionKey !== null ? props.partitionKey : '__none__'
      ),
    {
      refetchInterval: autoRefresh ? REFRESH_INTERVAL : false,
      enabled: shouldQuery
    }
  );

  const { data: currentFocusStepsData } = useQuery(
    ['steps', currentFocusAppID, currentFocusPartitionKey],
    () =>
      DefaultService.getApplicationLogsApiV0ProjectIdAppIdPartitionKeyAppsGet(
        projectId as string,
        currentFocusAppID as string,
        currentFocusPartitionKey !== null ? currentFocusPartitionKey : '__none__'
      ),
    {
      refetchInterval: autoRefresh ? REFRESH_INTERVAL : false,
      enabled: currentFocusAppID !== appID && currentFocusAppID !== undefined
    }
  );
  // TODO -- use a skiptoken to bypass annotation loading if we don't need them
  const { data: annotationsData, refetch: refetchAnnotationsData } = useQuery(
    ['annotations', appID, partitionKey],
    () =>
      DefaultService.getAnnotationsApiV0ProjectIdAnnotationsGet(
        projectId as string,
        appID as string,
        partitionKey !== null ? partitionKey : '__none__'
      ),
    {
      refetchInterval: autoRefresh ? REFRESH_INTERVAL : false,
      enabled: shouldQuery && props.allowAnnotations && backendSpec?.supports_annotations
    }
  );

  const { data: currentFocusAnnotationsData } = useQuery(
    ['annotations', currentFocusAppID, currentFocusPartitionKey],
    () =>
      DefaultService.getAnnotationsApiV0ProjectIdAnnotationsGet(
        projectId as string,
        currentFocusAppID as string,
        currentFocusPartitionKey !== null ? partitionKey : '__none__'
      ),
    {
      enabled:
        shouldQuery &&
        props.allowAnnotations &&
        backendSpec?.supports_annotations &&
        currentFocusAppID !== appID &&
        currentFocusAppID !== undefined
    }
  );

  const createAnnotationMutation = useMutation(
    (data: {
      projectId: string;
      annotationData: AnnotationCreate;
      appID: string;
      partitionKey: string | null;
      sequenceID: number;
    }) =>
      DefaultService.createAnnotationApiV0ProjectIdAppIdPartitionKeySequenceIdAnnotationsPost(
        projectId,
        appID,
        data.partitionKey !== null ? data.partitionKey : '__none__',
        data.sequenceID,
        data.annotationData
      )
  );

  const updateAnnotationMutation = useMutation(
    (data: { annotationID: number; annotationData: AnnotationUpdate }) =>
      DefaultService.updateAnnotationApiV0ProjectIdAnnotationIdUpdateAnnotationsPut(
        projectId,
        data.annotationID,
        data.annotationData
      )
  );

  useEffect(() => {
    const steps = data?.steps || [];
    const maxSequenceID = Math.max(...steps.map((step) => step.step_start_log.sequence_id));
    const minSequenceID = Math.min(...steps.map((step) => step.step_start_log.sequence_id));
    const handleKeyDown = (event: KeyboardEvent) => {
      switch (event.key) {
        case topToBottomChronological ? 'ArrowUp' : 'ArrowDown':
          if (
            currentSequenceLocation === undefined ||
            currentSequenceLocation.sequenceId <= minSequenceID
          ) {
            setCurrentSequenceLocation({
              appId: appID,
              partitionKey: partitionKey,
              sequenceId: minSequenceID
            });
          } else {
            setCurrentSequenceLocation({
              ...currentSequenceLocation,
              sequenceId: currentSequenceLocation.sequenceId - 1
            });
            // semtCurrentActionIndex(currentActionIndex - 1);
          }
          break;
        case topToBottomChronological ? 'ArrowDown' : 'ArrowUp':
          // case 'ArrowUp':
          if (currentSequenceLocation === undefined) {
            setCurrentSequenceLocation({
              appId: appID,
              partitionKey: partitionKey,
              sequenceId: maxSequenceID
            });
          } else if (currentSequenceLocation.sequenceId >= maxSequenceID) {
            // setCurrentActionIndex(currentActionIndex);
          } else {
            setCurrentSequenceLocation({
              ...currentSequenceLocation,
              sequenceId: currentSequenceLocation.sequenceId + 1
            });
            // setCurrentActionIndex(currentActionIndex + 1);
          }
          break;
        default:
          break;
      }
    };

    document.addEventListener('keydown', handleKeyDown);

    return () => {
      document.removeEventListener('keydown', handleKeyDown);
    };
  }, [data?.steps, currentSequenceLocation, setCurrentSequenceLocation]);
  useEffect(() => {
    if (autoRefresh) {
      const maxSequenceID = Math.max(
        ...(data?.steps.map((step) => step.step_start_log.sequence_id) || [])
      );
      setCurrentSequenceLocation({
        appId: appID,
        partitionKey: partitionKey,
        sequenceId: maxSequenceID
      });
    }
  }, [data, autoRefresh]);
  if (!shouldQuery) {
    return <Navigate to={'/projects'} />;
  }

  if (error) return <div>Error loading steps</div>;
  if (data === undefined || backendSpec === undefined) {
    return <Loading />;
  }
  const displayAnnotations = props.allowAnnotations && backendSpec.supports_annotations;
  // TODO -- re-enable this if I want...
  // const previousActions =
  //   currentActionIndex !== undefined
  //     ? getPriorActions(currentActionIndex, data.steps, NUM_PREVIOUS_ACTIONS)
  //     : currentActionIndex;
  const stepsCopied = [...data.steps];
  const stepsSorted = stepsCopied.sort((a, b) => {
    // Parse dates to get time in milliseconds
    const sequenceA = a.step_start_log.sequence_id;
    const sequenceB = b.step_start_log.sequence_id;
    if (sequenceA !== sequenceB) {
      return sequenceB - sequenceA;
    }
    const timeA = new Date(a.step_start_log.start_time).getTime();
    const timeB = new Date(b.step_start_log.start_time).getTime();

    // If times are equal down to milliseconds, compare microseconds
    if (timeA === timeB) {
      const microA = parseInt(a.step_start_log.start_time.slice(-6));
      const microB = parseInt(b.step_start_log.start_time.slice(-6));

      // Compare microseconds
      return microB - microA;
    }

    // Otherwise, compare milliseconds
    return timeB - timeA;
  });
  const Layout = props.orientation === 'stacked_horizontal' ? TwoColumnLayout : TwoRowLayout;
  const currentStep = stepsSorted.find(
    (step) =>
      step.step_start_log.sequence_id === currentSequenceLocation?.sequenceId &&
      appID === currentSequenceLocation?.appId &&
      partitionKey === currentSequenceLocation?.partitionKey
  );
  const hoverAction = hoverIndex
    ? stepsSorted.find(
        (step) =>
          step.step_start_log.sequence_id === hoverIndex.sequenceId &&
          appID === hoverIndex.appId &&
          partitionKey === hoverIndex.partitionKey
      )
    : undefined;

  return (
    <AppContext.Provider
      value={{
        attributesHighlighted: highlightedAttributes,
        setAttributesHighlighted: setHighlightedAttributes,
        setTab: setCurrentTab,
        tab: currentTab,
        setCurrentSelectedIndex: (loc) => {
          setCurrentSequenceLocation(loc);
          setInspectViewOpen(loc !== undefined);
        },
        currentSelectedIndex: currentSequenceLocation,
        setCurrentHoverIndex: setHoverIndex,
        currentHoverIndex: hoverIndex,
        currentEditingAnnotationContext: currentEditingAnnotationContext,
        setCurrentEditingAnnotationContext: setCurrentEditingAnnotationContext,
        // TODO -- handle span ID
        createAnnotation: async (
          projectId,
          partitionKey,
          appId,
          sequenceId,
          spanId,
          annotation
        ) => {
          const response = await createAnnotationMutation.mutateAsync({
            projectId: projectId,
            partitionKey: partitionKey,
            annotationData: annotation,
            appID: appId as string,
            sequenceID: sequenceId
          });
          await refetchAnnotationsData();
          return response;
        },
        updateAnnotation: async (annotationID, annotation) => {
          const response = await updateAnnotationMutation.mutateAsync({
            annotationID: annotationID,
            annotationData: annotation
          });
          await refetchAnnotationsData();
          return response;
        },
        refreshAnnotationData: refetchAnnotationsData
      }}
    >
      <Layout
        mode={fullScreen ? 'expanding-second' : minimizedTable ? 'first-minimal' : 'half'}
        firstItem={
          <div className="w-full h-full flex flex-col">
            <div
              className={`w-full ${fullScreen ? 'h-full' : props.orientation === 'stacked_vertical' ? 'h-full' : 'h-1/2'}`}
            >
              <ApplicationTable
                steps={stepsSorted}
                appID={appID}
                partitionKey={partitionKey}
                numPriorIndices={NUM_PREVIOUS_ACTIONS}
                autoRefresh={autoRefresh}
                setAutoRefresh={setAutoRefresh}
                minimized={minimizedTable}
                setMinimized={setMinimizedTable}
                projectId={projectId}
                parentPointer={data?.parent_pointer || undefined}
                spawningParentPointer={data?.spawning_parent_pointer || undefined}
                links={data.children || []}
                fullScreen={fullScreen}
                setFullScreen={setFullScreen}
                allowFullScreen={props.enableFullScreenStepView}
                allowMinimized={props.enableMinimizedStepView}
                topToBottomChronological={topToBottomChronological}
                setTopToBottomChronological={setTopToBottomChronological}
                toggleInspectViewOpen={() => setInspectViewOpen(!inspectViewOpen)}
                displayAnnotations={displayAnnotations}
                annotations={annotationsData || []}
              />
            </div>
            {!fullScreen && props.orientation === 'stacked_horizontal' && (
              <div className="h-1/2 w-[full]">
                <GraphView
                  stateMachine={data.application}
                  currentAction={currentStep}
                  // highlightedActions={previousActions}
                  highlightedActions={undefined}
                  hoverAction={hoverAction}
                />
              </div>
            )}
          </div>
        }
        secondItem={
          <AppStateView
            steps={currentFocusStepsData?.steps || stepsSorted}
            stateMachine={currentFocusStepsData?.application || data.application}
            // stateMachine={data.application}
            // highlightedActions={previousActions}
            highlightedActions={undefined}
            hoverAction={hoverAction}
            currentActionLocation={currentSequenceLocation}
            displayGraphAsTab={displayGraphAsTabs} // in this case we want the graph as a tab
            setMinimized={(min: boolean) => setInspectViewOpen(!min)}
            isMinimized={!inspectViewOpen}
            allowMinimized={inspectViewOpen && fullScreen}
            // TODO -- render better if this is undefined -- this is an odd way to fall back
            annotations={currentFocusAnnotationsData || annotationsData}
            restrictTabs={props.restrictTabs}
            allowAnnotations={displayAnnotations}
          />
        }
        animateSecondPanel={inspectViewOpen}
      />
    </AppContext.Provider>
  );
};

export const AppViewContainer = () => {
  const { projectId, appId, partitionKey } = useLocationParams();
  return (
    <AppView
      projectId={projectId}
      appId={appId}
      partitionKey={partitionKey}
      orientation={'stacked_horizontal'}
      enableFullScreenStepView={true}
      enableMinimizedStepView={true}
      allowAnnotations={true}
    />
  );
};
