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

import { useContext, useEffect, useMemo, useState } from 'react';
import {
  AnnotationCreate,
  AnnotationDataPointer,
  AnnotationObservation,
  AnnotationOut,
  AnnotationUpdate,
  DefaultService,
  Step
} from '../../../api';
import { AppView, AppContext } from './AppView';

import Select, { components } from 'react-select';
import CreatableSelect from 'react-select/creatable';
import { FaClipboardList, FaExternalLinkAlt, FaThumbsDown, FaThumbsUp } from 'react-icons/fa';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '../../common/table';
import { Chip } from '../../common/chip';
import { Link } from 'react-router-dom';
import { useMutation, useQuery } from '@tanstack/react-query';
import { Loading } from '../../common/loading';
import {
  ChevronDownIcon,
  PencilIcon,
  PencilSquareIcon,
  PlusIcon,
  XMarkIcon
} from '@heroicons/react/24/outline';
import { classNames } from '../../../utils/tailwind';
import { DateTimeDisplay } from '../../common/dates';
import { Drawer } from '../../common/drawer';
import { useLocationParams } from '../../../utils';

export const InlineAppView = (props: {
  projectId: string;
  partitionKey: string | null;
  appId: string;
  sequenceID: number;
}) => {
  return (
    <div className="w-full h-[40em]">
      <AppView
        projectId={props.projectId}
        appId={props.appId}
        orientation="stacked_horizontal"
        defaultAutoRefresh={false}
        enableFullScreenStepView={false}
        enableMinimizedStepView={false}
        allowAnnotations={false}
        restrictTabs={['data', 'code', 'reproduce', 'insights', 'graph']}
        disableNavigateSteps={false}
        forceCurrentActionIndex={{
          sequenceId: props.sequenceID,
          appId: props.appId,
          partitionKey: props.partitionKey
        }}
        partitionKey={props.partitionKey}
        forceFullScreen={true}
      />
    </div>
  );
};

const getAnnotationsTarget = (steps: Step[]) => {
  return steps.map((step) => ({
    sequenceId: step.step_start_log.sequence_id,
    spanId: null, // TODO -- allow annotations at the attribute/trace level!
    actionName: step.step_start_log.action
  }));
};

const getPossibleDataTargets = (step: Step) => {
  return [
    ...step.attributes.map((attribute) => ({
      type: AnnotationDataPointer.type.ATTRIBUTE,
      field_name: attribute.key,
      span_id: attribute.span_id,
      value: JSON.stringify(attribute.value)
    })),
    ...Object.keys(step.step_end_log?.state || {})
      .map((key) => ({
        type: AnnotationDataPointer.type.STATE_FIELD,
        field_name: key,
        span_id: null,
        value: JSON.stringify(step.step_end_log?.state[key])
      }))
      .filter((data) => !data.field_name.startsWith('__'))
  ];
};

export const AnnotationsView = (props: {
  currentStep: Step | undefined;
  appId: string;
  partitionKey: string | null;
  projectId: string;
  allAnnotations: AnnotationOut[];
  allSteps: Step[]; // List of steps so we can select the possible targets to annotate
}) => {
  const {
    currentEditingAnnotationContext,
    setCurrentEditingAnnotationContext,
    setCurrentHoverIndex,
    setCurrentSelectedIndex,
    createAnnotation,
    updateAnnotation,
    refreshAnnotationData
  } = useContext(AppContext);
  const tags = Array.from(new Set(props.allAnnotations.flatMap((annotation) => annotation.tags)));
  const annotationTargets = getAnnotationsTarget(props.allSteps);
  const selectedAnnotationTarget =
    currentEditingAnnotationContext === undefined
      ? undefined
      : {
          sequenceId: currentEditingAnnotationContext.sequenceId,
          spanId: null,
          actionName:
            props.allSteps.find(
              (step) =>
                step.step_start_log.sequence_id === currentEditingAnnotationContext.sequenceId
            )?.step_start_log.action || ''
        };
  const existingAnnotation = props.allAnnotations.find(
    (annotation) =>
      annotation.step_sequence_id === currentEditingAnnotationContext?.sequenceId &&
      annotation.app_id === props.appId &&
      annotation.span_id === currentEditingAnnotationContext.spanId
  );

  const step = existingAnnotation
    ? props.allSteps.find(
        (step) => step.step_start_log.sequence_id === existingAnnotation?.step_sequence_id
      )
    : props.allSteps.find(
        (step) => step.step_start_log.sequence_id === currentEditingAnnotationContext?.sequenceId
      );

  const allPossibleDataTargets: AnnnotationDataPointerWithValue[] = step
    ? getPossibleDataTargets(step)
    : [];

  return (
    <div>
      {currentEditingAnnotationContext && (
        <AnnotationEditCreateForm
          tagOptions={tags}
          allAnnotationTargets={annotationTargets}
          selectedAnnotationTarget={selectedAnnotationTarget}
          existingAnnotation={existingAnnotation}
          resetAnnotationContext={() => {
            setCurrentEditingAnnotationContext(undefined);
          }}
          createAnnotation={(annotation) => {
            createAnnotation(
              props.projectId,
              props.partitionKey,
              props.appId,
              currentEditingAnnotationContext.sequenceId,
              currentEditingAnnotationContext.spanId || undefined,
              annotation
            ).then(() => {
              refreshAnnotationData();
              setCurrentEditingAnnotationContext(undefined);
            });
          }}
          allPossibleDataTargets={allPossibleDataTargets}
          updateAnnotation={(annotationID, annotationUpdate) => {
            updateAnnotation(annotationID, annotationUpdate).then(() => {
              refreshAnnotationData();
              setCurrentEditingAnnotationContext(undefined);
            });
          }}
        />
      )}
      <AnnotationsTable
        annotations={props.allAnnotations}
        onClick={(annotation) => {
          // TODO -- ensure that the indices are aligned/set correctly
          setCurrentSelectedIndex({
            sequenceId: annotation.step_sequence_id,
            appId: props.appId,
            partitionKey: props.partitionKey
          });
        }}
        onHover={(annotation) => {
          setCurrentHoverIndex({
            sequenceId: annotation.step_sequence_id,
            appId: props.appId,
            partitionKey: props.partitionKey
          });
        }}
        displayProjectLevelAnnotationsLink={true} // we want to link back to the project level view
        projectId={props.projectId}
        highlightedSequence={
          currentEditingAnnotationContext ? currentEditingAnnotationContext.sequenceId : undefined
        }
      />
    </div>
  );
};

type DownloadButtonProps = {
  data: AnnotationOut[];
  fileName: string;
};
const annotationsToCSV = (annotations: AnnotationOut[]): string => {
  // Define the CSV headers
  const headers = [
    'id',
    'project_id',
    'app_id',
    'span_id',
    'step_sequence_id',
    'step_name',
    'tags',
    'observation_number',
    'note',
    'ground_truth',
    'thumbs_up_thumbs_down',
    'data_field_type',
    'data_field_name',
    'partition_key',
    'created',
    'updated'
  ];

  // Helper function to escape fields for CSV format
  const escapeCSV = (value: string) => {
    if (value === undefined) {
      return '';
    }
    if (value.includes(',') || value.includes('"') || value.includes('\n')) {
      return `"${value.replace(/"/g, '""')}"`;
    }
    return value;
  };

  // Convert the annotations to CSV format
  const rows = annotations.flatMap((annotation) => {
    return annotation.observations.map((observation, i) => {
      return {
        id: annotation.id.toString(),
        project_id: annotation.project_id,
        app_id: annotation.app_id,
        span_id: annotation.span_id || '',
        step_sequence_id: annotation.step_sequence_id.toString(),
        step_name: annotation.step_name,
        tags: annotation.tags.join(' '),
        observation_number: i.toString(),
        note: observation.data_fields['note'] || '',
        ground_truth: observation.data_fields['ground_truth'] || '',
        thumbs_up_thumbs_down:
          observation.thumbs_up_thumbs_down !== null
            ? observation.thumbs_up_thumbs_down.toString()
            : '',
        data_field_type: observation.data_pointers.map((dp) => dp.type).join(' '),
        data_field_name: observation.data_pointers.map((dp) => dp.field_name).join(' '),
        partition_key: annotation.partition_key || '',
        created: new Date(annotation.created).toISOString(),
        updated: new Date(annotation.updated).toISOString()
      };
    });
  });

  // Construct the CSV string -- TODO -- use a library for this
  const csvContent = [
    headers.join(','), // Add headers
    ...rows.map((row) =>
      headers.map((header) => escapeCSV(row[header as keyof typeof row])).join(',')
    ) // Add data rows
  ].join('\n');

  return csvContent;
};

const DownloadAnnotationsButton: React.FC<DownloadButtonProps> = ({ data, fileName }) => {
  const handleDownload = () => {
    const csvData = annotationsToCSV(data);
    const blob = new Blob([csvData], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.setAttribute('download', fileName);
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
  };

  return (
    <button
      onClick={handleDownload}
      className="px-4 py-2 h-10 text-sm bg-dwlightblue text-white rounded-md hover:bg-dwlightblue/70 cursor-pointer"
    >
      Download
    </button>
  );
};

type TagOptionType = {
  value: string;
  label: string;
};

type AnnotationTarget = {
  sequenceId: number;
  actionName: string;
  spanId: string | null;
};

type TargetOptionType = {
  value: AnnotationTarget;
  label: string;
};

const getLabelForTarget = (target: AnnotationTarget) =>
  `${target.actionName}:${target.sequenceId}` + (target.spanId ? `-${target.spanId}` : '');

const ObservationsView = (props: { observations: AnnotationObservation[] }) => {
  // Observation -- this will be a list of notes with data attached
  // Data -- a chip with the type of the data (state, attribute) + key, with link
  // Thumbs up/down -- a thumbs up or thumbs down icon
  // Notes -- free-form text
  // This is going to expand to show the data and the notes, otherwise it'll just be truncated
  const [isExpanded, setIsExpanded] = useState(false);
  const observationsToShow = isExpanded ? props.observations : props.observations.slice(0, 1);
  return (
    <div
      className={`flex flex-col max-w-96 w-96 cursor-cell ${isExpanded ? 'whitespace-pre-line' : 'truncate'}`}
      onClick={(e) => {
        setIsExpanded((expanded) => !expanded);
        e.preventDefault();
      }}
    >
      {observationsToShow.map((observation, i) => {
        const Icon = observation.thumbs_up_thumbs_down ? FaThumbsUp : FaThumbsDown;
        const iconColor = observation.thumbs_up_thumbs_down ? 'text-green-500' : 'text-dwred';
        return (
          <div
            key={i}
            className={`flex flex-col gap-1 ${i === observationsToShow.length - 1 ? '' : 'border-b-2'}  border-gray-100`}
          >
            <div className={`flex flex-row gap-2 max-w-full items-baseline `}>
              {observation.thumbs_up_thumbs_down !== null && (
                <div className="translate-y-1">
                  <Icon className={iconColor} size={16} />
                </div>
              )}
              <div className="flex flex-row gap-2 pt-1">
                {observation.data_pointers.map((dataPointer, i) => (
                  <div key={i.toString()} className="flex flex-row gap-1">
                    <Chip
                      label={`${dataPointer.type === 'state_field' ? 'state' : 'attribute'}`}
                      chipType={`${dataPointer.type === 'state_field' ? 'annotateDataPointerState' : 'annotateDataPointerAttribute'}`}
                    />
                    <pre>.{dataPointer.field_name}</pre>
                  </div>
                ))}
              </div>
            </div>
            <div className="flex flex-grow justify-between flex-col">
              {observation.data_fields['note'] && (
                <div className="">
                  {' '}
                  <span className="text-gray-400 pr-2">Note</span>
                  {observation.data_fields['note']}
                </div>
              )}
              {observation.data_fields['ground_truth'] && (
                <div className="">
                  {' '}
                  <span className="text-gray-400 pr-2">Ground Truth:</span>
                  {observation.data_fields['ground_truth']}
                </div>
              )}
              {!isExpanded && props.observations.length > 1 && (
                <span className="text-gray-400 text-sm">
                  +{`${props.observations.length - 1} more`}
                </span>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
};

type Filters = {
  tags?: string[];
  actionNames?: string[];
};

type SearchBarProps = {
  filters: Filters;
  setFilters: (filters: Filters) => void;
  data: AnnotationOut[];
};

const SearchBar: React.FC<SearchBarProps> = ({ filters, setFilters, data }) => {
  // Options for react-select derived from the data
  const options = useMemo(() => {
    // Use Sets to ensure uniqueness
    const tagSet = new Set<string>();
    const actionNameSet = new Set<string>();

    // Populate the sets with unique tags and action names
    data.forEach((annotation) => {
      annotation.tags.forEach((tag) => tagSet.add(tag));
      actionNameSet.add(annotation.step_name);
    });

    // Convert sets to the format required for react-select
    const tagOptions = Array.from(tagSet).map((tag) => ({ value: tag, label: tag, type: 'tag' }));
    const actionNameOptions = Array.from(actionNameSet).map((name) => ({
      value: name,
      label: name,
      type: 'actionName'
    }));

    return [...tagOptions, ...actionNameOptions];
  }, [data]);

  // Handle selection from react-select
  // TODO -- remove anys here
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const handleChange = (selectedOptions: any) => {
    const newFilters: Filters = {
      tags: selectedOptions

        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        .filter((option: any) => option.type === 'tag')

        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        .map((option: any) => option.value),
      actionNames: selectedOptions

        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        .filter((option: any) => option.type === 'actionName')

        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        .map((option: any) => option.value)
    };
    setFilters(newFilters);
  };
  const selectedOptions = options.filter((option) => {
    return (
      (filters.tags && filters.tags.includes(option.value)) ||
      (filters.actionNames && filters.actionNames.includes(option.value))
    );
  });

  const OptionType = (props: { type: 'actionName' | 'tag'; value: string }) => {
    const { type, value } = props;
    return (
      <div className="flex flex-row gap-2">
        <Chip
          chipType={type === 'tag' ? 'tag' : 'action'}
          label={type === 'tag' ? 'tag' : 'action'}
        />
        <span>{value}</span>
      </div>
    );
  };
  return (
    <Select
      options={options}
      onChange={handleChange}
      value={selectedOptions}
      isMulti
      placeholder="Search annotations by tag/action. Tags are *AND* queries, actions are *OR* queries."
      className="w-full"
      components={{
        Option: (props) => (
          <components.Option {...props}>
            <OptionType type={props.data.type as 'tag' | 'actionName'} value={props.data.value} />
          </components.Option>
        ),
        MultiValue: (props) => (
          <components.MultiValue {...props}>
            <OptionType type={props.data.type as 'tag' | 'actionName'} value={props.data.value} />
          </components.MultiValue>
        )
      }}
    />
  );
};

const filterData = (data: AnnotationOut[], filters: Filters) => {
  let filteredData = data;
  const tags = filters.tags;
  if (tags !== undefined && tags.length > 0) {
    filteredData = filteredData.filter((annotation) =>
      tags.every((tag) => annotation.tags.includes(tag))
    );
  }

  const actions = filters.actionNames;

  if (actions !== undefined && actions.length > 0) {
    filteredData = filteredData.filter((annotation) => actions.includes(annotation.step_name));
  }

  return filteredData;
};
export const AnnotationsTable = (props: {
  annotations: AnnotationOut[];
  projectId: string;
  onHover?: ((annotation: AnnotationOut) => void) | undefined;
  onClick?: ((annotation: AnnotationOut) => void) | undefined;
  highlightedSequence?: number;
  displayProjectLevelAnnotationsLink?: boolean;
  displayAppLevelIdentifiers?: boolean;
  displayInlineAppView?: boolean;
  displayTimestamps?: boolean;
  displaySearchBar?: boolean;
  allowInlineEdit?: boolean;
  refetchAnnotations?: () => void;
}) => {
  // Just in case we want to do live-updating, we need to pass it into the form...
  const updateAnnotationMutation = useMutation({
    mutationFn: (data: { annotationID: number; annotationData: AnnotationUpdate }) =>
      DefaultService.updateAnnotationApiV0ProjectIdAnnotationIdUpdateAnnotationsPut(
        props.projectId,
        data.annotationID,
        data.annotationData
      ),
    onSuccess: () => {
      props.refetchAnnotations && props.refetchAnnotations();
      setCurrentlyEditingAnnotation(null); // We have to reset it somehow
    }
  });
  const anyHavePartitionKey = props.annotations.some(
    (annotation) => annotation.partition_key !== null
  );
  const displayPartitionKeyColumn = anyHavePartitionKey && props.displayAppLevelIdentifiers;
  const displayAppIdColumn = props.displayAppLevelIdentifiers;
  const [expandedAnnotation, setExpandedAnnotation] = useState<AnnotationOut | null>(null);

  const [filters, setFilters] = useState<Filters>({});

  const sortedFilteredAnnotations = filterData(
    [...props.annotations].sort((a, b) => (a.step_sequence_id > b.step_sequence_id ? 1 : -1)),
    filters
  );

  // When this is open a modal will be open too for editing
  const [currentlyEditingAnnotation, setCurrentlyEditingAnnotation] =
    useState<AnnotationOut | null>(null);

  const annotationTarget = {
    sequenceId: currentlyEditingAnnotation?.step_sequence_id || 0,
    actionName: currentlyEditingAnnotation?.step_name || '',
    spanId: currentlyEditingAnnotation?.span_id || null
  };
  const { data: appData } = useQuery({
    queryKey: ['steps', currentlyEditingAnnotation?.app_id],
    queryFn: () =>
      DefaultService.getApplicationLogsApiV0ProjectIdAppIdPartitionKeyAppsGet(
        props.projectId,
        currentlyEditingAnnotation?.app_id as string,
        currentlyEditingAnnotation?.partition_key as string
      ),
    enabled: currentlyEditingAnnotation !== null
  });
  // Either we're editing one that exists, or we're creating a new one...
  // TODO -- simplify the logic here, we should have one path...
  const annotationStep = currentlyEditingAnnotation
    ? // Editing an existing annotation
      appData?.steps.find(
        (step) => step.step_start_log.sequence_id === currentlyEditingAnnotation?.step_sequence_id
      )
    : // Creating a new annotation
      appData?.steps.find(
        (step) => step.step_start_log.sequence_id === annotationTarget.sequenceId
      );
  return (
    <div className="w-full h-full">
      <Drawer
        title="Edit Annotation"
        open={currentlyEditingAnnotation !== null}
        close={() => {
          setCurrentlyEditingAnnotation(null);
        }}
      >
        {/* gate for type-checking, really this won't be open unless there is one */}
        {currentlyEditingAnnotation && (
          <AnnotationEditCreateForm
            tagOptions={Array.from(
              new Set(props.annotations.flatMap((annotation) => annotation.tags))
            )}
            allAnnotationTargets={[annotationTarget]}
            selectedAnnotationTarget={annotationTarget}
            existingAnnotation={currentlyEditingAnnotation as AnnotationOut}
            resetAnnotationContext={function (): void {
              setCurrentlyEditingAnnotation(null);
            }}
            createAnnotation={function (): void {}}
            updateAnnotation={function (annotationID: number, annotation: AnnotationUpdate): void {
              updateAnnotationMutation.mutate({
                annotationID: annotationID,
                annotationData: annotation
              });
            }}
            allPossibleDataTargets={annotationStep ? getPossibleDataTargets(annotationStep) : []}
          />
        )}
      </Drawer>
      {props.displaySearchBar && (
        <div className="w-full px-4 py-2 flex flex-row gap-2">
          <SearchBar filters={filters} setFilters={setFilters} data={props.annotations} />
          <DownloadAnnotationsButton data={sortedFilteredAnnotations} fileName="annotations.csv" />
        </div>
      )}
      <Table dense={1}>
        <TableHead>
          <TableRow>
            {props.displayInlineAppView && <TableHeader className=""></TableHeader>}
            {displayPartitionKeyColumn && <TableHeader className="">Partition Key</TableHeader>}
            {props.displayTimestamps && <TableHeader className="">Updated at</TableHeader>}
            {props.displayAppLevelIdentifiers && <TableHeader className="">App ID</TableHeader>}

            <TableHeader className="">Step</TableHeader>
            {/* <TableHeader className=""></TableHeader> */}
            {/* <TableHeader className="">Span</TableHeader> */}
            <TableHeader className="">Tags</TableHeader>
            <TableHeader className="">Observations</TableHeader>
            <TableHeader colSpan={1}>
              {props.displayProjectLevelAnnotationsLink ? (
                <Link to={`/annotations/${props.projectId}`}>
                  <FaExternalLinkAlt className="text-gray-500 w-3 h-3 hover:scale-125" />
                </Link>
              ) : (
                <></>
              )}
            </TableHeader>
            <TableHeader />
            {props.allowInlineEdit && <TableHeader className="w-6"></TableHeader>}
          </TableRow>
        </TableHead>
        <TableBody>
          {sortedFilteredAnnotations.map((annotation) => {
            const isExpanded = expandedAnnotation?.id === annotation.id;
            // const ThumbsUpIcon = annotation.thumbs_up_thumbs_down ? FaThumbsUp : FaThumbsDown;
            const selected = annotation.step_sequence_id === props.highlightedSequence;
            // const thumbsUpColor = annotation.thumbs_up_thumbs_down
            //   ? 'text-green-500'
            //   : 'text-dwred';
            return (
              <>
                <TableRow
                  key={annotation.id}
                  className={`cursor-pointer ${selected ? 'bg-gray-200' : 'hover:bg-gray-50'}`}
                  onClick={() => {
                    if (props.onClick) {
                      props.onClick(annotation);
                    }
                  }}
                  onMouseEnter={() => {
                    if (props.onHover) {
                      props.onHover(annotation);
                    }
                  }}
                >
                  {props.displayInlineAppView && (
                    <TableCell className="w-6 align-top">
                      {' '}
                      <ChevronDownIcon
                        className={classNames(
                          isExpanded ? 'rotate-180 text-gray-500' : 'text-gray-400',
                          'ml-auto h-5 w-5 shrink-0'
                        )}
                        aria-hidden="true"
                        onClick={() => {
                          setExpandedAnnotation(isExpanded ? null : annotation);
                        }}
                      />
                    </TableCell>
                  )}
                  {props.displayTimestamps && (
                    <TableCell className="align-top">
                      <DateTimeDisplay date={annotation.updated} mode={'short'} />
                    </TableCell>
                  )}
                  {displayPartitionKeyColumn && (
                    <TableCell>
                      <Link
                        className="hover:underline text-dwlightblue cursor-pointer"
                        to={`/project/${props.projectId}/${annotation.partition_key}`}
                      >
                        {annotation.partition_key}
                      </Link>
                    </TableCell>
                  )}
                  {displayAppIdColumn && (
                    <TableCell className="align-top">
                      <Link
                        className="hover:underline text-dwlightblue cursor-pointer"
                        to={`/project/${props.projectId}/${annotation.partition_key}/${annotation.app_id}`}
                      >
                        {annotation.app_id}
                      </Link>
                    </TableCell>
                  )}
                  <TableCell className="align-top">
                    <div className="align-top flex flex-row gap-1 items-baseline">
                      <Chip label={`action: ${annotation.step_sequence_id}`} chipType="action" />
                      <Link
                        className="flex flex-row gap-1 hover:underline text-dwlightblue cursor-pointer"
                        to={`/project/${props.projectId}/${annotation.partition_key}/${annotation.app_id}?sequence_id=${annotation.step_sequence_id}&tab=annotations`}
                      >
                        {/* <span>{annotation.step_sequence_id}</span> */}
                        {annotation.span_id !== null && <span>{`:${annotation.span_id}`}</span>}
                        <span>({annotation.step_name})</span>
                      </Link>
                    </div>
                  </TableCell>
                  <TableCell className="align-top">
                    <div className="flex flex-row gap-1 max-w-96 flex-wrap">
                      {annotation.tags.map((tag, i) => (
                        <Chip key={i} label={tag} chipType="tag" />
                      ))}
                    </div>
                  </TableCell>
                  <TableCell className="align-top">
                    <ObservationsView observations={annotation.observations} />
                  </TableCell>
                  <TableCell />
                  {props.allowInlineEdit && (
                    <TableCell className="align-top">
                      <AnnotateButton
                        appID={annotation.app_id}
                        partitionKey={annotation.partition_key}
                        sequenceID={annotation.step_sequence_id}
                        spanID={annotation.span_id || undefined}
                        existingAnnotation={annotation}
                        setCurrentEditingAnnotationContext={(context) => {
                          setCurrentlyEditingAnnotation(
                            context.existingAnnotation as AnnotationOut
                          );
                        }}
                      />
                    </TableCell>
                  )}
                </TableRow>
                <TableRow className="w-full">
                  {isExpanded && (
                    <TableCell className="" colSpan={16}>
                      <div className="px-10">
                        <InlineAppView
                          projectId={props.projectId}
                          partitionKey={annotation.partition_key}
                          appId={annotation.app_id}
                          sequenceID={annotation.step_sequence_id}
                        ></InlineAppView>
                      </div>
                    </TableCell>
                  )}
                </TableRow>
              </>
            );
          })}
        </TableBody>
      </Table>
      {props.annotations.length === 0 && (
        <div className="flex flex-row justify-center items-center h-96">
          <div className="text-gray-400 text-lg flex flex-row gap-1">
            No annotations found -- go to an application run and click on an entry in the
            annnotations column <PencilIcon className="h-6 w-6" /> to add annotations.
          </div>
        </div>
      )}
    </div>
  );
};

const getEmptyObservation = (): AnnotationObservation => ({
  data_fields: {
    note: '',
    ground_truth: ''
  },
  thumbs_up_thumbs_down: null,
  data_pointers: []
});

const ObservationForm = (props: {
  observation: AnnotationObservation;
  addObservation: () => void;
  removeObservation: () => void;
  setObservation: (observation: AnnotationObservation) => void;
  allowDelete: boolean;
  possibleDataTargets: AnnnotationDataPointerWithValue[];
}) => {
  const observation = props.observation;
  const thumbsUp = observation.thumbs_up_thumbs_down;
  const [showGroundTruth, setShowGroundTruth] = useState(
    Boolean(observation.data_fields['ground_truth'])
  );
  const toggleThumbsUp = (clickedThumbsUp: boolean) => {
    if (thumbsUp === clickedThumbsUp) {
      observation.thumbs_up_thumbs_down = null;
    } else {
      observation.thumbs_up_thumbs_down = clickedThumbsUp;
    }
    props.setObservation(observation);
  };

  const possibleDataTargetValues =
    props.possibleDataTargets.map((dataPointer) => ({
      value: dataPointer,
      label: `${dataPointer.type}:${dataPointer.field_name}`
    })) || [];
  return (
    <div className="flex flex-col">
      <div className="flex flex-row gap-2">
        <div className="flex space-x-2">
          <button>
            <FaThumbsUp
              className={`text-green-500 hover:scale-110 ${thumbsUp !== true ? 'opacity-50' : ''}`}
              size={16}
              onClick={() => toggleThumbsUp(true)}
            />
          </button>
          <button>
            <FaThumbsDown
              className={`text-dwred hover:scale-110 ${thumbsUp !== false ? 'opacity-50' : ''}`}
              size={16}
              onClick={() => toggleThumbsUp(false)}
            />
          </button>
        </div>
        <div className="flex flex-grow">
          <Select
            options={possibleDataTargetValues}
            value={
              possibleDataTargetValues.find(
                (option) =>
                  option.value.field_name === observation.data_pointers[0]?.field_name &&
                  option.value.type === observation.data_pointers[0]?.type
              ) || null
            }
            onChange={(selectedOption) => {
              if (selectedOption === null) return;
              observation.data_pointers = [selectedOption.value];
              props.setObservation(observation);
            }}
            placeholder="Select data (fields in state/attributes) associated with your observation"
            styles={{
              placeholder: (provided) => ({
                ...provided,
                whiteSpace: 'nowrap',
                overflow: 'hidden',
                textOverflow: 'ellipsis'
              }),
              control: (provided) => ({
                ...provided,
                resize: 'horizontal'
              })
            }}
            className="w-full"
            // TODO: Create and use a custom component for the menu items
            components={{
              Option: (props) => {
                // TODO: Customize the menu item component here
                return (
                  <components.Option {...props}>
                    {' '}
                    <div className="flex flex-row gap-2">
                      <Chip
                        chipType={
                          props.data.value.type === 'state_field'
                            ? 'annotateDataPointerState'
                            : 'annotateDataPointerAttribute'
                        }
                        label={props.data.value.type}
                      />
                      <span>{props.data.value.field_name}</span>
                      <pre>{props.data.value.value}</pre>
                    </div>
                  </components.Option>
                );
              },
              SingleValue: (props) => {
                // TODO: Customize the selected item component here
                return (
                  <components.SingleValue {...props}>
                    <div className="flex flex-row gap-2">
                      <Chip
                        chipType={
                          props.data.value.type === 'state_field'
                            ? 'annotateDataPointerState'
                            : 'annotateDataPointerAttribute'
                        }
                        label={props.data.value.type}
                      />
                      <span>{props.data.value.field_name}</span>
                      {/* <pre>{props.data.value.value}</pre> */}
                    </div>
                  </components.SingleValue>
                );
              }
            }}
          />
        </div>
        <button
          className="w-10 inline-flex justify-center items-center rounded-md bg-green-600 px-3 py-2 text-sm font-semibold text-white shadow-sm hover:bg-green-600/70 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-gray-700/70"
          disabled={observation.data_fields['ground_truth']}
          onClick={() => {
            setShowGroundTruth((show) => !show);
          }}
        >
          <FaClipboardList className="h-4 w-4" />
        </button>

        {props.allowDelete && (
          <button
            className="w-10 inline-flex justify-center items-center rounded-md bg-dwred/80 px-3 py-2 text-sm font-semibold text-white shadow-sm hover:bg-gray-600/70 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-gray-700/70"
            onClick={() => {
              props.removeObservation();
            }}
          >
            <XMarkIcon className="h-6 w-6" />
          </button>
        )}
        <button
          className="w-10 inline-flex justify-center items-center rounded-md bg-dwdarkblue/80 px-3 py-2 text-sm font-semibold text-white shadow-sm hover:bg-gray-600/70 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-gray-700/70"
          onClick={() => {
            props.addObservation();
          }}
        >
          {'+'}
        </button>
      </div>
      {observation.data_pointers.length > 0 && (
        <pre className=" text-sm mt-2 whitespace-pre-wrap">
          {
            possibleDataTargetValues.find(
              (option) =>
                option.value.field_name === observation.data_pointers[0]?.field_name &&
                option.value.type === observation.data_pointers[0]?.type
            )?.value.value
          }
        </pre>
      )}
      <div className="flex flex-col mt-2 items-baseline gap-2">
        <div className="text text-gray-500 text-md min-w-max">Notes</div>
        <textarea
          placeholder="Notes about the annotation go here..."
          value={observation.data_fields['note']}
          rows={4}
          className="block w-full rounded-md border-0 p-2 text-gray-900 shadow-sm ring-1 ring-inset ring-gray-300 placeholder:text-gray-400 focus:ring-2 focus:ring-inset focus:ring-dwlightblue/30 sm:text-sm sm:leading-6"
          defaultValue={''}
          onChange={(e) => {
            observation.data_fields['note'] = e.target.value;
            props.setObservation(observation);
          }}
        />
      </div>
      {(showGroundTruth || observation.data_fields['ground_truth']) && (
        <div className="flex flex-col mt-2 items-baseline gap-2">
          <div className="text text-gray-500 text-md min-w-max">Ground truth </div>
          <textarea
            placeholder="Enter a ground-truth (optional)"
            value={observation.data_fields['ground_truth']}
            rows={4}
            className="resize-none block w-full hide-scrollbar rounded-md border-0 p-2 text-gray-900 shadow-sm ring-1 ring-inset ring-gray-300 placeholder:text-gray-400 focus:ring-2 focus:ring-inset focus:ring-dwlightblue/30 sm:text-sm sm:leading-6"
            defaultValue={''}
            onChange={(e) => {
              observation.data_fields['ground_truth'] = e.target.value;
              props.setObservation(observation);
            }}
          ></textarea>
        </div>
      )}
    </div>
  );
};
type AnnnotationDataPointerWithValue = AnnotationDataPointer & { value: string };

export const AnnotateButton = (props: {
  appID: string;
  partitionKey: string | null;
  sequenceID: number;
  spanID?: string;
  attribute?: string; // TODO -- consider whether we want to remove, we generally annotate at the step level
  // But we might want to prepopulate the attribute if we are annotating a specific attribute (in the observations field)
  existingAnnotation: AnnotationOut | undefined;
  setCurrentEditingAnnotationContext: (context: {
    appId: string;
    partitionKey: string | null;
    sequenceId: number;
    attributeName: string | undefined;
    spanId: string | null;
    existingAnnotation: AnnotationOut | undefined;
  }) => void;
  // setTab: (tab: string) => void; // used if we want to change tab for view
}) => {
  const Icon = props.existingAnnotation ? PencilSquareIcon : PlusIcon;
  return (
    <Icon
      className="hover:scale-125 h-4 w-4"
      onClick={(e) => {
        props.setCurrentEditingAnnotationContext({
          appId: props.appID,
          partitionKey: props.partitionKey,
          sequenceId: props.sequenceID,
          attributeName: props.attribute,
          spanId: props.spanID || null,
          existingAnnotation: props.existingAnnotation
        });
        e.stopPropagation();
        e.preventDefault();
      }}
    />
  );
};

const DEFAULT_TAG_OPTIONS = [
  'to-review',
  'hallucination',
  'incomplete',
  'incorrect',
  'correct',
  'ambiguous',
  'user-error',
  'intentional-user-error'
];
const AnnotationEditCreateForm = (props: {
  tagOptions: string[];
  allAnnotationTargets: AnnotationTarget[];
  selectedAnnotationTarget: AnnotationTarget | undefined;
  existingAnnotation: AnnotationOut | undefined; // Only there if we are editing an existing annotation
  resetAnnotationContext: () => void;
  createAnnotation: (annotation: AnnotationCreate) => void;
  updateAnnotation: (annotationID: number, annotation: AnnotationUpdate) => void;
  allPossibleDataTargets: AnnnotationDataPointerWithValue[];
}) => {
  const [targetValue, setTargetValue] = useState<TargetOptionType | null>(null);

  const [tags, setTags] = useState<TagOptionType[]>([]);

  // const [attribute, setAttribute] = useState<string>('');
  const [observations, setObservations] = useState<AnnotationObservation[]>([
    getEmptyObservation()
  ]);

  // Define options for the select components

  const tagOptions: TagOptionType[] = [...DEFAULT_TAG_OPTIONS, ...props.tagOptions].map((tag) => ({
    value: tag,
    label: tag
  }));

  const allTargets = props.allAnnotationTargets.map((target) => ({
    value: target,
    label: getLabelForTarget(target)
  }));

  useEffect(() => {
    // Reset to the selected annotation if it exists
    if (props.existingAnnotation) {
      setTargetValue({
        value: {
          sequenceId: props.existingAnnotation.step_sequence_id,
          actionName: props.existingAnnotation.step_name,
          spanId: props.existingAnnotation.span_id
        },
        label: getLabelForTarget({
          sequenceId: props.existingAnnotation.step_sequence_id,
          actionName: props.existingAnnotation.step_name,
          spanId: props.existingAnnotation.span_id
        })
      });
      setObservations(props.existingAnnotation.observations);
      setTags(
        props.existingAnnotation.tags.map((tag) => ({
          value: tag,
          label: tag
        }))
      );
      // Otherwise, create a new one
      // } else if (props.selectedAnnotationTarget) {
      //   setTargetValue({
      //     value: props.selectedAnnotationTarget,
      //     label: getLabelForTarget(props.selectedAnnotationTarget)
      //   });
    }
  }, [props.existingAnnotation]);

  useEffect(() => {
    if (props.selectedAnnotationTarget && !props.existingAnnotation) {
      setTargetValue({
        value: props.selectedAnnotationTarget,
        label: getLabelForTarget(props.selectedAnnotationTarget)
      });
      setTags([]);
      setObservations([getEmptyObservation()]);
    }
  }, [props.selectedAnnotationTarget?.sequenceId]);
  const TagChipOption = (props: { label: string; chipType: string }) => {
    return (
      <div className="flex flex-row gap-2">
        <Chip label={props.label} chipType={'tag'} />
      </div>
    );
  };
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const handleTagChange = (selectedOptions: any) => {
    setTags(selectedOptions ? selectedOptions.map((option: TagOptionType) => option) : []);
  };
  const mode = props.existingAnnotation !== undefined ? 'edit' : 'create';

  return (
    <div className="p-4 space-y-4">
      <Select
        options={allTargets}
        value={targetValue}
        onChange={(selectedOption) => setTargetValue(selectedOption)}
        placeholder="Select an option..."
        className="basic-single"
        classNamePrefix="select"
      />
      <CreatableSelect
        options={tagOptions}
        isMulti
        value={tags}
        onChange={handleTagChange}
        placeholder="Select tags/create new"
        className="basic-multi-select"
        classNamePrefix="select"
        components={{
          Option: (props) => (
            <components.Option {...props}>
              <TagChipOption label={props.data.value} chipType="tag" />
            </components.Option>
          ),
          MultiValue: (props) => (
            <components.MultiValue {...props}>
              <TagChipOption label={props.data.value} chipType="tag" />
            </components.MultiValue>
          )
        }}
      />
      <h1 className="text-md font-semibold text-gray-600">Observations </h1>
      {observations.map((observation, i) => {
        const allowDelete = observations.length > 1;
        return (
          <ObservationForm
            key={i}
            observation={observation}
            addObservation={() => {
              setObservations([...observations, getEmptyObservation()]);
            }}
            removeObservation={() => {
              setObservations(observations.filter((_, index) => index !== i));
            }}
            allowDelete={allowDelete}
            setObservation={(observation) => {
              setObservations(observations.map((obs, index) => (index === i ? observation : obs)));
            }}
            possibleDataTargets={props.allPossibleDataTargets}
          />
        );
      })}
      <div className="flex flex-row justify-end items-center gap-2">
        {/* <div className="flex-grow"> */}
        {/* <div className="text-sm min-w-max text-gray-500">Ground truth (optional) </div> */}

        {/* </div> */}
        <div className="flex flex-row gap-2">
          <button
            onClick={props.resetAnnotationContext}
            className="w-fullinline-flex items-center rounded-md bg-dwred/80 px-3 py-2 text-sm font-semibold text-white shadow-sm hover:bg-dwred/30 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-dwred/70"
          >
            {'Cancel'}
          </button>
          <button
            onClick={() => {
              if (mode === 'create') {
                props.createAnnotation({
                  observations: observations,
                  tags: tags.map((tag) => tag.value),
                  span_id: targetValue?.value.spanId || null,
                  step_name: targetValue?.value.actionName || ''
                });
              } else {
                props.updateAnnotation(props.existingAnnotation?.id as number, {
                  observations: observations,
                  tags: tags.map((tag) => tag.value),
                  span_id: targetValue?.value.spanId || null,
                  step_name: targetValue?.value.actionName || ''
                });
              }
            }}
            type="submit"
            className="w-fullinline-flex items-center rounded-md bg-dwlightblue/80 px-3 py-2 text-sm font-semibold text-white shadow-sm hover:bg-dwlightblue/30 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-dwlightblue/30"
          >
            {mode === 'edit' ? 'Update' : 'Create'}
          </button>
        </div>
      </div>
    </div>
  );
};
/**
 * Annotations view for the application -- this is the top-level project view
 * @returns
 */
export const AnnotationsViewContainer = () => {
  const { projectId } = useLocationParams();
  const { data: backendSpec } = useQuery({
    queryKey: ['backendSpec'],
    queryFn: () =>
      DefaultService.getAppSpecApiV0MetadataAppSpecGet().then((response) => {
        return response;
      })
  });

  // TODO -- use a skiptoken to bypass annotation loading if we don't need them
  const { data, refetch } = useQuery({
    queryKey: ['annotations', projectId],
    queryFn: () => DefaultService.getAnnotationsApiV0ProjectIdAnnotationsGet(projectId as string)
  });
  // dummy value as this will not be linked to if annotations are not supported

  if (data === undefined || backendSpec === undefined) return <Loading />;
  return (
    <AnnotationsTable
      annotations={data}
      projectId={projectId as string}
      displayAppLevelIdentifiers
      displayInlineAppView
      displayTimestamps
      displaySearchBar
      allowInlineEdit
      refetchAnnotations={refetch}
    />
  );
};
