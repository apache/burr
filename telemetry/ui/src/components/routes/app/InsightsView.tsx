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

import { AttributeModel, Span, Step } from '../../../api';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '../../common/table';
import React, { useContext, useState } from 'react';
import { ChevronDownIcon, ChevronUpIcon } from '@heroicons/react/24/outline';
import { AppContext } from './AppView';
import { Chip } from '../../common/chip';
import { modelCosts } from '../../common/modelCost';

/**
 * Insights allow us to visualize and surface attributes stored in steps.
 * The common use-case is LLM calls -- we want to summarize tokens, prompts, etc...
 * That said, we could also use it for loss functions on ML training, whatnot
 * Eventually we will be moving this to the server side and make it at a project level, but this is
 * a good start (at the app level).
 *
 * Insights are an aggregation over attributes
 */
type InsightBase = {
  // Tells the category
  category: 'llm' | 'metric';
  // Tells whether or not we have the insight, meaning whether it should register or not
  hasInsight: (allAttributes: AttributeModel[]) => boolean;
  // Name of the insight
  insightName: string;
  // The insight value
  RenderInsightValue: React.FC<{ attributes: AttributeModel[] }>;
};

/**
 * We want to allow them to expose individual values, but we may change the types here
 * later. Basically we have a simple flag on whether they show individual values (E.g if they're an aggregation),
 * and if they do, we have a function to capture them and a function to render them.
 *
 * These are undefined if we do not.
 *
 * Code will likely be repeated between this and the hasInsight/RenderInsightValue, but we'll keep it separate
 * for now.
 */

type InsightWithIndividualValues = InsightBase & {
  // Captures individual values for the insight -- allows you to expand out
  captureIndividualValues: (allAttributes: AttributeModel[]) => AttributeModel[];
  // Render the individual values
  RenderIndividualValue: React.FC<{ attribute: AttributeModel }>;
};

type InsightWithoutIndividualValues = InsightBase & {
  captureIndividualValues?: never;
  RenderIndividualValue?: never;
};

type Insight = InsightWithIndividualValues | InsightWithoutIndividualValues;

// eslint-disable-next-line @typescript-eslint/no-unused-vars
const getCostPerTokenModelDollars = (model: string) => {
  // TODO -- unhardcode this!
  const promptCost = modelCosts[model]?.input_cost_per_token || 0;
  const completionCost = modelCosts[model]?.output_cost_per_token || 0;
  return { promptCost, completionCost };
  // return { promptCost: 500 / 1_000_000, completionCost: 500 / 1_000_000 };
};

type CostProps = {
  totalCost: number;
  costDetails?: {
    costPerPromptToken: number;
    costPerCompletionToken: number;
    promptTokens: number;
    completionTokens: number;
  };
  currency?: string;
};
const Cost: React.FC<CostProps> = ({ currency = 'USD', totalCost, costDetails }) => {
  const [showDetails, setShowDetails] = useState(false);

  // Determine the number of decimal places needed, up to a maximum of 5

  // Inline function to apply decimal places logic
  const applyDecimalPlaces = (num: number) => {
    const decimalPlaces = Math.min((num.toString().split('.')[1] || '').length, 5);
    return num.toFixed(decimalPlaces);
  };
  const decimalPlaces = Math.min((totalCost.toString().split('.')[1] || '').length, 5);

  // Format the number with dynamic decimal places
  const formattedCost = new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: currency,
    minimumFractionDigits: decimalPlaces,
    maximumFractionDigits: decimalPlaces
  }).format(totalCost);

  return (
    <div className="relative bg-dwlightblue/10 text-dwdarkblue text-sm font-medium px-2 py-1 rounded-sm">
      <div
        onMouseLeave={() => setShowDetails(false)}
        onMouseEnter={() => setShowDetails((prev) => !prev)}
        className="cursor-pointer"
      >
        {formattedCost}
      </div>
      {costDetails && showDetails && (
        <div className="absolute right-full top-0 h-full w-min min-w-max p-3 bg-white  border-gray-200 z-50 rounded-sm flex flex-row items-center">
          <p className="flex flex-row gap-0 justify-center items-center p-2">
            {'$'}
            {applyDecimalPlaces(totalCost)} = {costDetails.promptTokens} prompt tokens * {'$'}
            {applyDecimalPlaces(costDetails.costPerPromptToken)} + {costDetails.completionTokens}{' '}
            completion tokens * {'$'}
            {applyDecimalPlaces(costDetails.costPerCompletionToken)}
          </p>
        </div>
      )}
    </div>
  );
};

type CostAttributeModel = AttributeModel & {
  value: {
    promptTokens: number;
    completionTokens: number;
    costPerPromptToken: number;
    costPerCompletionToken: number;
  };
};

const gatherCostAttributes = (allAttributes: AttributeModel[]): CostAttributeModel[] => {
  const modelAttributesBySpanID = allAttributes.reduce((acc, attribute) => {
    if (attribute.key === 'gen_ai.response.model') {
      acc.set(attribute.span_id || '', attribute);
    }
    return acc;
  }, new Map<string, AttributeModel>());

  const tokensUsedBySpanID = allAttributes.reduce((acc, attribute) => {
    if (attribute.key === 'gen_ai.usage.completion_tokens') {
      const currentValue = acc.get(attribute.span_id || '') || { prompt: 0, completion: 0 };
      acc.set(attribute.span_id || '', {
        prompt: currentValue.prompt,
        completion: currentValue.completion + (attribute.value as number)
      });
    }
    if (attribute.key === 'gen_ai.usage.prompt_tokens') {
      const currentValue = acc.get(attribute.span_id || '') || { prompt: 0, completion: 0 };
      acc.set(attribute.span_id || '', {
        prompt: currentValue.prompt + (attribute.value as number),
        completion: currentValue.completion
      });
    }
    return acc;
  }, new Map<string, { prompt: number; completion: number }>());
  const costDataBySpanID = new Map<
    string,
    {
      promptTokens: number;
      completionTokens: number;
      costPerPromptToken: number;
      costPerCompletionToken: number;
    }
  >();
  tokensUsedBySpanID.forEach((tokensUsed, spanID) => {
    const modelAttribute = modelAttributesBySpanID.get(spanID);
    if (modelAttribute) {
      const { promptCost, completionCost } = getCostPerTokenModelDollars(
        modelAttribute.value as string
      );
      // console.log('promptCost', promptCost, 'completionCost', completionCost, 'tokensUsed', tokensUsed);
      costDataBySpanID.set(
        spanID,
        {
          promptTokens: tokensUsed.prompt,
          completionTokens: tokensUsed.completion,
          costPerPromptToken: promptCost,
          costPerCompletionToken: completionCost
        }
        // tokensUsed.prompt * promptCost + tokensUsed.completion * completionCost
      );
    }
  });
  return Array.from(costDataBySpanID.entries()).map(([spanID, cost]) => {
    const modelAttribute = modelAttributesBySpanID.get(spanID);
    return {
      key: spanID,
      action_sequence_id: modelAttribute?.action_sequence_id || 0,
      value: cost,
      span_id: spanID,
      timestamp: modelAttribute?.time_logged || 0,
      tags: {}
    };
  });
};

const REGISTERED_INSIGHTS: Insight[] = [
  {
    category: 'llm',
    hasInsight: (allAttributes) => {
      return allAttributes.some(
        (attribute) => attribute.key.endsWith('prompt_tokens') && attribute.key.startsWith('gen_ai')
      );
    },
    insightName: 'Total Prompt Tokens',
    RenderInsightValue: (props) => {
      let totalPromptTokens = 0;
      props.attributes.forEach((attribute) => {
        if (attribute.key.endsWith('prompt_tokens') && attribute.key.startsWith('gen_ai')) {
          totalPromptTokens += attribute.value as number;
        }
      });
      return <p>{totalPromptTokens}</p>;
    },
    captureIndividualValues: (allAttributes) => {
      return allAttributes.filter(
        (attribute) => attribute.key.endsWith('prompt_tokens') && attribute.key.startsWith('gen_ai')
      );
    },
    RenderIndividualValue: (props: { attribute: AttributeModel }) => {
      return <p>{props.attribute.value?.toString()}</p>;
    }
  },
  {
    category: 'llm',
    hasInsight: (allAttributes) => {
      return allAttributes.some(
        (attribute) =>
          attribute.key.endsWith('completion_tokens') && attribute.key.startsWith('gen_ai')
      );
    },
    insightName: 'Total Completion Tokens',
    RenderInsightValue: (props) => {
      let totalCompletionTokens = 0;
      props.attributes.forEach((attribute) => {
        if (attribute.key.endsWith('completion_tokens')) {
          totalCompletionTokens += attribute.value as number;
        }
      });
      return <p>{totalCompletionTokens}</p>;
    },
    captureIndividualValues: (allAttributes) => {
      return allAttributes.filter(
        (attribute) =>
          attribute.key.endsWith('completion_tokens') && attribute.key.startsWith('gen_ai')
      );
    },
    RenderIndividualValue: (props: { attribute: AttributeModel }) => {
      return <p>{props.attribute.value?.toString()}</p>;
    }
  },
  {
    category: 'llm',
    hasInsight: (allAttributes) => {
      return allAttributes.some(
        (attribute) => attribute.key.endsWith('prompt_tokens') && attribute.key.startsWith('gen_ai')
      );
    },
    insightName: 'Total LLM Calls',
    RenderInsightValue: (props) => {
      let totalLLMCalls = 0;
      props.attributes.forEach((attribute) => {
        if (attribute.key.endsWith('prompt_tokens') && attribute.key.startsWith('gen_ai')) {
          totalLLMCalls += 1;
        }
      });
      return <p>{totalLLMCalls}</p>;
    },
    captureIndividualValues: (allAttributes) => {
      const spanIDToLLMCalls = new Map<string, number>();
      allAttributes.forEach((attribute) => {
        if (attribute.key.endsWith('prompt_tokens') && attribute.key.startsWith('gen_ai')) {
          spanIDToLLMCalls.set(
            attribute.span_id || '',
            (spanIDToLLMCalls.get(attribute.span_id || '') || 0) + 1
          );
        }
      });
      return Array.from(spanIDToLLMCalls.entries()).map(([spanID, count]) => {
        return {
          key: 'llm_calls',
          action_sequence_id: 0,
          value: count,
          span_id: spanID,
          timestamp: 0,
          tags: {}
        };
      });
      // return allAttributes.filter((attribute) => attribute.key.endsWith('prompt_tokens')).map;
    },
    RenderIndividualValue: (props: { attribute: AttributeModel }) => {
      return <p>{props.attribute.value?.toString()}</p>;
    }
  },
  {
    category: 'llm',
    hasInsight: (allAttributes) => {
      return allAttributes.some(
        (attribute) => attribute.key.endsWith('prompt_tokens') && attribute.key.startsWith('gen_ai')
      );
    },
    insightName: 'Total LLM Cost',
    RenderInsightValue: (props) => {
      const costAttributes = gatherCostAttributes(props.attributes);
      let totalCost = 0;
      costAttributes.forEach((attribute) => {
        totalCost +=
          attribute.value.promptTokens * attribute.value.costPerPromptToken +
          attribute.value.completionTokens * attribute.value.costPerCompletionToken;
      });
      return <Cost totalCost={totalCost} />;
    },
    captureIndividualValues: (allAttributes) => {
      return gatherCostAttributes(allAttributes);
    },
    RenderIndividualValue: (props: { attribute: AttributeModel }) => {
      const cast = props.attribute as CostAttributeModel;
      return (
        <Cost
          totalCost={
            cast.value.promptTokens * cast.value.costPerPromptToken +
            cast.value.completionTokens * cast.value.costPerCompletionToken
          }
          costDetails={{
            costPerPromptToken: cast.value.costPerPromptToken,
            costPerCompletionToken: cast.value.costPerCompletionToken,
            promptTokens: cast.value.promptTokens,
            completionTokens: cast.value.completionTokens
          }}
        />
      );
      // return <p>{props.attribute.value?.toString()}</p>;
    }
  }
];

// TODO -- get anonymous insights
const InsightSubTable = (props: {
  attributes: AttributeModel[];
  insight: Insight;
  allSpans: Span[];
  allSteps: Step[];
  appID: string;
  partitionKey: string | null;
}) => {
  const individualValues = props.insight.captureIndividualValues?.(props.attributes);
  const [isExpanded, setIsExpanded] = React.useState(false);
  const ExpandIcon = isExpanded ? ChevronUpIcon : ChevronDownIcon;
  const canExpand = props.insight.captureIndividualValues !== undefined;
  const spansBySpanID = props.allSpans.reduce((acc, span) => {
    acc.set(span.begin_entry.span_id, span);
    return acc;
  }, new Map<string, Span>());
  const stepsByStepID = props.allSteps.reduce((acc, step) => {
    acc.set(step.step_start_log.sequence_id, step);
    return acc;
  }, new Map<number, Step>());

  const { currentSelectedIndex, setCurrentSelectedIndex, currentHoverIndex, setCurrentHoverIndex } =
    useContext(AppContext);

  return (
    <>
      <TableRow
        className="hover:bg-gray-50 cursor-pointer "
        onClick={() => {
          if (canExpand) {
            setIsExpanded(!isExpanded);
          }
        }}
      >
        <TableCell>
          <div className="flex flex-row gap-1 items-center">
            <Chip label={props.insight.category} chipType={props.insight.category}></Chip>
            {props.insight.insightName}
          </div>
        </TableCell>
        <TableCell className=""></TableCell>
        <TableCell className=""></TableCell>

        <TableCell className="flex flex-row justify-end gap-2">
          <props.insight.RenderInsightValue attributes={props.attributes} />
          {canExpand ? (
            <button>
              <ExpandIcon className="h-5 w-5" />
            </button>
          ) : (
            <></>
          )}
        </TableCell>
      </TableRow>
      {isExpanded
        ? individualValues?.map((attribute, i) => {
            const span = spansBySpanID.get(attribute.span_id || '');
            const step = stepsByStepID.get(span?.begin_entry.action_sequence_id || 0);
            const insightCasted = props.insight as InsightWithIndividualValues;
            const isHovered = currentHoverIndex === span?.begin_entry.action_sequence_id;
            const isCurrentSelected = currentSelectedIndex === span?.begin_entry.action_sequence_id;
            return (
              <TableRow
                key={attribute.key + i}
                className={` ${isCurrentSelected ? 'bg-gray-200' : isHovered ? 'bg-gray-50' : 'hover:bg-gray-50'} cursor-pointer`}
                onMouseEnter={() => {
                  setCurrentHoverIndex(
                    span
                      ? {
                          sequenceId: span.begin_entry.action_sequence_id,
                          appId: props.appID,
                          partitionKey: props.partitionKey
                        }
                      : undefined
                  );
                }}
                onMouseLeave={() => {
                  setCurrentHoverIndex(undefined);
                }}
                onClick={() => {
                  setCurrentSelectedIndex(
                    span
                      ? {
                          sequenceId: span.begin_entry.action_sequence_id,
                          appId: props.appID,
                          partitionKey: props.partitionKey
                        }
                      : undefined
                  );
                }}
              >
                <TableCell></TableCell>
                <TableCell className="">
                  {step && (
                    <div className="flex gap-2">
                      <span>{step.step_start_log.action}</span>
                      <span>({span?.begin_entry.action_sequence_id})</span>
                    </div>
                  )}
                </TableCell>
                <TableCell className="">
                  <div className="flex gap">
                    <div>{span?.begin_entry.span_name || ''}</div>
                    <div className="pl-2">({attribute.span_id?.split(':')})</div>
                  </div>
                </TableCell>
                <TableCell className="flex justify-end mr-7">
                  <insightCasted.RenderIndividualValue attribute={attribute} />
                </TableCell>
              </TableRow>
            );
          })
        : null}
    </>
  );
};

export const InsightsView = (props: {
  steps: Step[];
  appId: string;
  partitionKey: string | null;
}) => {
  const allAttributes: AttributeModel[] = props.steps.flatMap((step) => step.attributes);

  const allSpans = props.steps.flatMap((step) => step.spans);

  const out = (
    <div className="pt-0 flex flex-col hide-scrollbar">
      <Table dense={1}>
        <TableHead>
          <TableRow className="hover:bg-gray-100">
            <TableHeader className="w-72">Name </TableHeader>
            <TableHeader className="w-48">Step</TableHeader>
            <TableHeader className="w-48">Span</TableHeader>
            <TableHeader className="flex justify-end">Value</TableHeader>
            {/* <TableHeader colSpan={1}></TableHeader> */}
          </TableRow>
        </TableHead>
        <TableBody>
          {REGISTERED_INSIGHTS.map((insight) => {
            if (insight.hasInsight(allAttributes)) {
              return (
                <InsightSubTable
                  key={insight.insightName}
                  attributes={allAttributes}
                  insight={insight}
                  allSpans={allSpans}
                  allSteps={props.steps}
                  appID={props.appId}
                  partitionKey={props.partitionKey}
                />
              );
            }
          })}
        </TableBody>
      </Table>
      <div>
        <h2 className="text-gray-500 pl-2 pt-4">
          Use this tab to view summaries of your application. This automatically picks up on a
          variety of attributes, including those populated by{' '}
          <a
            className="text-dwlightblue"
            href={'https://www.traceloop.com/docs/openllmetry/tracing/without-sdk'}
          >
            opentelemetry instrumentation.
          </a>{' '}
          -- E.G. LLM call data. To instrument, and start collecting, see{' '}
          <a
            className="text-dwlightblue"
            href={'https://burr.apache.org/concepts/additional-visibility/#quickstart'}
          >
            see docs.
          </a>
        </h2>
      </div>
    </div>
  );
  return out;
};
