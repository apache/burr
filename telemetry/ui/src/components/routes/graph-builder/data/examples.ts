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

export interface ExampleGraph {
  id: string;
  title: string;
  description: string;
  nodes: Array<{
    id: string;
    label: string;
    nodeType: 'input' | 'action';
    isAsync?: boolean;
    isStreaming?: boolean;
    position: { x: number; y: number };
    description?: string;
  }>;
  edges: Array<{
    id: string;
    source: string;
    target: string;
    condition?: string;
    isConditional: boolean;
  }>;
}

export const multiModalChatbotWorkflow: ExampleGraph = {
  id: 'multi-modal-chatbot',
  title: 'MultiModal Chatbot',
  description: 'A ChatGPT-like bot which supports multiple response modes, with regular actions.',
  nodes: [
    {
      id: 'node_prompt',
      label: 'prompt',
      nodeType: 'action',
      position: { x: 761, y: 91 }
    },
    {
      id: 'node_check_openai_key',
      label: 'check_openai_key',
      nodeType: 'action',
      position: { x: 591, y: 193 }
    },
    {
      id: 'node_check_safety',
      label: 'check_safety',
      nodeType: 'action',
      position: { x: 384, y: 342 }
    },
    {
      id: 'node_decide_mode',
      label: 'decide_mode',
      nodeType: 'action',
      position: { x: 245, y: 441 }
    },
    {
      id: 'node_prompt_for_more',
      label: 'prompt_for_more',
      nodeType: 'action',
      position: { x: 25, y: 640 }
    },
    {
      id: 'node_generate_image',
      label: 'generate_image',
      nodeType: 'action',
      position: { x: 237, y: 673 }
    },
    {
      id: 'node_generate_code',
      label: 'generate_code',
      nodeType: 'action',
      position: { x: 470, y: 747 }
    },
    {
      id: 'node_answer_question',
      label: 'answer_question',
      nodeType: 'action',
      position: { x: 1019, y: 724 }
    },
    {
      id: 'node_response',
      label: 'response',
      nodeType: 'action',
      position: { x: 883, y: 909 }
    },
    {
      id: 'input_prompt',
      label: 'input: prompt',
      nodeType: 'input',
      position: { x: 790, y: -29 }
    },
    {
      id: 'input_model',
      label: 'input: model',
      nodeType: 'input',
      position: { x: 884, y: 549 }
    },
    {
      id: 'input_display_type',
      label: 'input: display_type',
      nodeType: 'input',
      position: { x: 1086, y: 551 }
    }
  ],
  edges: [
    {
      id: 'e-input_prompt-node_prompt',
      source: 'input_prompt',
      target: 'node_prompt',
      isConditional: false
    },
    {
      id: 'e-node_prompt-node_check_openai_key',
      source: 'node_prompt',
      target: 'node_check_openai_key',
      isConditional: false
    },
    {
      id: 'e-node_check_openai_key-node_response',
      source: 'node_check_openai_key',
      target: 'node_response',
      isConditional: false
    },
    {
      id: 'e-node_check_openai_key-node_check_safety',
      source: 'node_check_openai_key',
      target: 'node_check_safety',
      condition: 'has_openai_key=True',
      isConditional: true
    },
    {
      id: 'e-node_check_safety-node_decide_mode',
      source: 'node_check_safety',
      target: 'node_decide_mode',
      condition: 'safe=True',
      isConditional: true
    },
    {
      id: 'e-node_check_safety-node_response',
      source: 'node_check_safety',
      target: 'node_response',
      isConditional: false
    },
    {
      id: 'e-node_decide_mode-node_prompt_for_more',
      source: 'node_decide_mode',
      target: 'node_prompt_for_more',
      isConditional: false
    },
    {
      id: 'e-node_decide_mode-node_generate_image',
      source: 'node_decide_mode',
      target: 'node_generate_image',
      condition: 'mode="generate_image"',
      isConditional: true
    },
    {
      id: 'e-node_decide_mode-node_generate_code',
      source: 'node_decide_mode',
      target: 'node_generate_code',
      condition: 'mode="generate_code"',
      isConditional: true
    },
    {
      id: 'e-node_decide_mode-node_answer_question',
      source: 'node_decide_mode',
      target: 'node_answer_question',
      condition: 'mode="answer_question"',
      isConditional: true
    },
    {
      id: 'e-node_answer_question-node_response',
      source: 'node_answer_question',
      target: 'node_response',
      isConditional: false
    },
    {
      id: 'e-node_generate_code-node_response',
      source: 'node_generate_code',
      target: 'node_response',
      isConditional: false
    },
    {
      id: 'e-node_generate_image-node_response',
      source: 'node_generate_image',
      target: 'node_response',
      isConditional: false
    },
    {
      id: 'e-node_prompt_for_more-node_response',
      source: 'node_prompt_for_more',
      target: 'node_response',
      isConditional: false
    },
    {
      id: 'e-node_response-node_prompt',
      source: 'node_response',
      target: 'node_prompt',
      isConditional: false
    },
    {
      id: 'e-input_model-node_generate_code',
      source: 'input_model',
      target: 'node_generate_code',
      isConditional: false
    },
    {
      id: 'e-input_model-node_answer_question',
      source: 'input_model',
      target: 'node_answer_question',
      isConditional: false
    },
    {
      id: 'e-input_model-node_generate_image',
      source: 'input_model',
      target: 'node_generate_image',
      isConditional: false
    },
    {
      id: 'e-input_display_type-node_answer_question',
      source: 'input_display_type',
      target: 'node_answer_question',
      isConditional: false
    },
    {
      id: 'e-input_display_type-node_generate_code',
      source: 'input_display_type',
      target: 'node_generate_code',
      isConditional: false
    }
  ]
};

export const streamingChatbotWorkflow: ExampleGraph = {
  id: 'streaming-chatbot',
  title: 'Streaming Chatbot',
  description: 'A ChatGPT-like bot which supports multiple response modes, with streaming actions.',
  nodes: [
    {
      id: 'input_prompt',
      label: 'input: prompt',
      nodeType: 'input',
      position: { x: 500, y: 50 }
    },
    {
      id: 'input_model',
      label: 'input: model',
      nodeType: 'input',
      position: { x: 84, y: 436 }
    },
    {
      id: 'prompt',
      label: 'prompt',
      nodeType: 'action',
      position: { x: 500, y: 200 }
    },
    {
      id: 'check_safety',
      label: 'check_safety',
      nodeType: 'action',
      position: { x: 500, y: 350 }
    },
    {
      id: 'decide_mode',
      label: 'decide_mode',
      nodeType: 'action',
      position: { x: 400, y: 500 }
    },
    {
      id: 'unsafe_response',
      label: 'unsafe_response',
      nodeType: 'action',
      isAsync: true,
      isStreaming: true,
      position: { x: 761, y: 496 }
    },
    {
      id: 'generate_code',
      label: 'generate_code',
      nodeType: 'action',
      isAsync: true,
      isStreaming: true,
      position: { x: 90, y: 635 }
    },
    {
      id: 'answer_question',
      label: 'answer_question',
      nodeType: 'action',
      isAsync: true,
      isStreaming: true,
      position: { x: 299, y: 713 }
    },
    {
      id: 'generate_poem',
      label: 'generate_poem',
      nodeType: 'action',
      isAsync: true,
      isStreaming: true,
      position: { x: 565, y: 780 }
    },
    {
      id: 'prompt_for_more',
      label: 'prompt_for_more',
      nodeType: 'action',
      isAsync: true,
      isStreaming: true,
      position: { x: 730, y: 677 }
    }
  ],
  edges: [
    {
      id: 'e-input_prompt-prompt',
      source: 'input_prompt',
      target: 'prompt',
      isConditional: false
    },
    {
      id: 'e-input_model-generate_code',
      source: 'input_model',
      target: 'generate_code',
      isConditional: false
    },
    {
      id: 'e-input_model-answer_question',
      source: 'input_model',
      target: 'answer_question',
      isConditional: false
    },
    {
      id: 'e-input_model-generate_poem',
      source: 'input_model',
      target: 'generate_poem',
      isConditional: false
    },
    {
      id: 'e-prompt-check_safety',
      source: 'prompt',
      target: 'check_safety',
      isConditional: false
    },
    {
      id: 'e-check_safety-decide_mode',
      source: 'check_safety',
      target: 'decide_mode',
      condition: 'safe=True',
      isConditional: true
    },
    {
      id: 'e-check_safety-unsafe_response',
      source: 'check_safety',
      target: 'unsafe_response',
      isConditional: false
    },
    {
      id: 'e-decide_mode-generate_code',
      source: 'decide_mode',
      target: 'generate_code',
      condition: 'mode="generate_code"',
      isConditional: true
    },
    {
      id: 'e-decide_mode-answer_question',
      source: 'decide_mode',
      target: 'answer_question',
      condition: 'mode="answer_question"',
      isConditional: true
    },
    {
      id: 'e-decide_mode-generate_poem',
      source: 'decide_mode',
      target: 'generate_poem',
      condition: 'mode="generate_poem"',
      isConditional: true
    },
    {
      id: 'e-decide_mode-prompt_for_more',
      source: 'decide_mode',
      target: 'prompt_for_more',
      isConditional: false
    },
    {
      id: 'e-generate_code-prompt',
      source: 'generate_code',
      target: 'prompt',
      isConditional: false
    },
    {
      id: 'e-answer_question-prompt',
      source: 'answer_question',
      target: 'prompt',
      isConditional: false
    },
    {
      id: 'e-generate_poem-prompt',
      source: 'generate_poem',
      target: 'prompt',
      isConditional: false
    },
    {
      id: 'e-unsafe_response-prompt',
      source: 'unsafe_response',
      target: 'prompt',
      isConditional: false
    },
    {
      id: 'e-prompt_for_more-prompt',
      source: 'prompt_for_more',
      target: 'prompt',
      isConditional: false
    }
  ]
};

export const adaptiveCRAGWorkflow: ExampleGraph = {
  id: 'adaptive-crag',
  title: 'Adaptive CRAG',
  description:
    'A system that dynamically selects the most suitable route for a given user query and self-reflects on retrieved documents to improve response quality.',
  nodes: [
    {
      id: 'node_router',
      label: 'router',
      nodeType: 'action',
      position: { x: 821, y: 177 }
    },
    {
      id: 'node_terminate',
      label: 'terminate',
      nodeType: 'action',
      position: { x: 1115, y: 339 }
    },
    {
      id: 'node_rewrite_query',
      label: 'rewrite_query_for_lancedb',
      nodeType: 'action',
      position: { x: 570, y: 343 }
    },
    {
      id: 'node_search_lancedb',
      label: 'search_lancedb',
      nodeType: 'action',
      position: { x: 395, y: 474 }
    },
    {
      id: 'node_remove_irrelevant',
      label: 'remove_irrelevant_lancedb_results',
      nodeType: 'action',
      position: { x: 222, y: 598 }
    },
    {
      id: 'node_extract_keywords',
      label: 'extract_keywords_for_exa_search',
      nodeType: 'action',
      position: { x: 862, y: 755 }
    },
    {
      id: 'node_search_exa',
      label: 'search_exa',
      nodeType: 'action',
      position: { x: 1014, y: 900 }
    },
    {
      id: 'node_ask_assistant',
      label: 'ask_assistant',
      nodeType: 'action',
      position: { x: 664, y: 1050 }
    },
    {
      id: 'input_query',
      label: 'input: query',
      nodeType: 'input',
      position: { x: 822, y: 26 }
    }
  ],
  edges: [
    {
      id: 'e-input_query-node_router',
      source: 'input_query',
      target: 'node_router',
      isConditional: false
    },
    {
      id: 'e-node_router-node_rewrite_query',
      source: 'node_router',
      target: 'node_rewrite_query',
      isConditional: false
    },
    {
      id: 'e-node_rewrite_query-node_search_lancedb',
      source: 'node_rewrite_query',
      target: 'node_search_lancedb',
      isConditional: false
    },
    {
      id: 'e-node_search_lancedb-node_remove_irrelevant',
      source: 'node_search_lancedb',
      target: 'node_remove_irrelevant',
      isConditional: false
    },
    {
      id: 'e-node_remove_irrelevant-node_ask_assistant',
      source: 'node_remove_irrelevant',
      target: 'node_ask_assistant',
      isConditional: false
    },
    {
      id: 'e-node_remove_irrelevant-node_extract_keywords',
      source: 'node_remove_irrelevant',
      target: 'node_extract_keywords',
      condition: 'len(lancedb_results) < docs_limit',
      isConditional: true
    },
    {
      id: 'e-node_extract_keywords-node_search_exa',
      source: 'node_extract_keywords',
      target: 'node_search_exa',
      isConditional: false
    },
    {
      id: 'e-node_search_exa-node_ask_assistant',
      source: 'node_search_exa',
      target: 'node_ask_assistant',
      isConditional: false
    },
    {
      id: 'e-node_router-node_ask_assistant',
      source: 'node_router',
      target: 'node_ask_assistant',
      condition: 'route="assistant"',
      isConditional: true
    },
    {
      id: 'e-node_router-node_extract_keywords',
      source: 'node_router',
      target: 'node_extract_keywords',
      condition: 'route="web_search"',
      isConditional: true
    },
    {
      id: 'e-node_router-node_terminate',
      source: 'node_router',
      target: 'node_terminate',
      condition: 'route="terminate"',
      isConditional: true
    }
  ]
};

export const examples = [multiModalChatbotWorkflow, adaptiveCRAGWorkflow, streamingChatbotWorkflow];
