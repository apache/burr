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

import { ComputerDesktopIcon, UserIcon } from '@heroicons/react/24/outline';
import { classNames } from '../utils/tailwind';
import { Button } from '../components/common/button';
import { TwoColumnLayout } from '../components/common/layout';
import { ApplicationSummary, ChatItem, DefaultService } from '../api';
import { KeyboardEvent, useEffect, useState } from 'react';
import { useQuery } from 'react-query';
import { Loading } from '../components/common/loading';
import Markdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { TelemetryWithSelector } from './Common';

type Role = 'assistant' | 'user';

/**
 * Simple chat history with instructions to start -- constant across everything.
 */
const DEFAULT_CHAT_HISTORY: ChatItem[] = [
  {
    role: ChatItem.role.ASSISTANT,
    content:
      '📖 Select a conversation from the list to get started! ' +
      'The left side of this is a simple chatbot. The right side is the same' +
      ' Burr Telemetry app you can see if you click through the [chatbot demo](/projects/demo_chatbot) project. Note that images ' +
      "will likely stop displaying after a while due to OpenAI's persistence policy. So generate some new ones! 📖",
    type: ChatItem.type.TEXT
  },
  {
    role: ChatItem.role.ASSISTANT,
    content:
      ' \n\n💡 This is meant to demonstrate the power of the Burr streaming capabilities! ' +
      'chat on the left while examining the internals of the chatbot on the right.💡',
    type: ChatItem.type.TEXT
  }
];

/**
 * Helper function to get the character based on the role -- this just selects how it renders
 * @param role Role of the character
 * @returns AI or You based on the role
 */
const getCharacter = (role: Role) => {
  return role === 'assistant' ? 'AI' : 'You';
};

/**
 * Component for the Icon based on the role
 */
const RoleIcon = (props: { role: Role }) => {
  const Icon = props.role === 'assistant' ? ComputerDesktopIcon : UserIcon;
  return (
    <Icon className={classNames('text-gray-400', 'ml-auto h-6 w-6 shrink-0')} aria-hidden="true" />
  );
};

// Constant so we can scroll to the latest
const VIEW_END_ID = 'end-view';

/**
 * React component to render a chat message. Can handle markdown.
 */
const ChatMessage = (props: { message: ChatItem; id?: string }) => {
  return (
    <div className="flex gap-3 my-4  text-gray-600 text-sm flex-1 w-full" id={props.id}>
      <span className="relative flex shrink-0">
        <RoleIcon role={props.message.role} />
      </span>
      <div className="leading-relaxed w-full">
        <span className="block font-bold text-gray-700">{getCharacter(props.message.role)} </span>
        {props.message.type === ChatItem.type.TEXT ||
        props.message.type === ChatItem.type.CODE ||
        props.message.type === ChatItem.type.ERROR ? (
          <Markdown
            components={{
              // Custom rendering for links
              a: ({ ...props }) => <a className="text-dwlightblue hover:underline" {...props} />
            }}
            remarkPlugins={[remarkGfm]}
            className={`whitespace-pre-wrap break-lines max-w-full ${props.message.type === ChatItem.type.ERROR ? 'bg-dwred/10' : ''} p-0.5`}>
            {props.message.content}
          </Markdown>
        ) : (
          <></>
        )}
      </div>
    </div>
  );
};

/**
 * Convenience function to scroll to the latest message in the chat.
 * This just sets the div to scroll to the bottom and sets up an observer to keep it there.
 */
const scrollToLatest = () => {
  const lastMessage = document.getElementById(VIEW_END_ID);
  if (lastMessage) {
    // Directly scroll to the bottom
    lastMessage.scrollTop = lastMessage.scrollHeight;

    // Setup an observer to auto-scroll on size changes
    const observer = new ResizeObserver(() => {
      lastMessage.scrollTop = lastMessage.scrollHeight;
    });
    observer.observe(lastMessage);

    // Cleanup observer on component unmount or updates
    return () => observer.disconnect();
  }
};

// Types for the chatbot stream -- we can't use react-query/openapi as they don't support streaming
// See
type Event = {
  type: 'delta' | 'chat_history';
};

type ChatMessageEvent = Event & {
  value: string;
};

type ChatHistoryEvent = Event & {
  value: ChatItem[];
};

/**
 * Streaming chatbot component -- renders chat + fetches from API
 */
export const StreamingChatbot = (props: { projectId: string; appId: string | undefined }) => {
  const [currentPrompt, setCurrentPrompt] = useState<string>('');
  const [displayedChatHistory, setDisplayedChatHistory] = useState(DEFAULT_CHAT_HISTORY);
  const [currentResponse, setCurrentResponse] = useState<string>('');
  const [isChatWaiting, setIsChatWaiting] = useState<boolean>(false);

  const { isLoading: isInitialLoading } = useQuery(
    // TODO -- handle errors
    ['chat', props.projectId, props.appId],
    () =>
      DefaultService.chatHistoryApiV0StreamingChatbotHistoryProjectIdAppIdGet(
        props.projectId,
        props.appId || '' // TODO -- find a cleaner way of doing a skip-token like thing here
      ),
    {
      enabled: props.appId !== undefined,
      onSuccess: (data) => {
        setDisplayedChatHistory(data); // when its succesful we want to set the displayed chat history
      },
      onError: (error: Error) => {
        setDisplayedChatHistory([
          ...DEFAULT_CHAT_HISTORY,
          {
            content: `Unable to load from server: ${error.message}`,
            role: ChatItem.role.ASSISTANT,
            type: ChatItem.type.ERROR
          }
        ]);
      }
    }
  );

  const submitPrompt = async () => {
    setCurrentResponse(''); // Reset it
    setIsChatWaiting(true);
    const basePath = window.__BURR_BASE_PATH__ || '';
    const response = await fetch(
      `${basePath}/api/v0/streaming_chatbot/response/${props.projectId}/${props.appId}`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ prompt: currentPrompt })
      }
    );
    const reader = response.body?.getReader();
    let chatResponse = '';
    if (reader) {
      const decoder = new TextDecoder('utf-8');
      // eslint-disable-next-line no-constant-condition
      while (true) {
        const result = await reader.read();
        if (result.done) {
          break;
        }
        const message = decoder.decode(result.value, { stream: true });
        message
          .split('data: ')
          .slice(1)
          .forEach((item) => {
            const event: Event = JSON.parse(item);
            if (event.type === 'chat_history') {
              const chatMessageEvent = event as ChatHistoryEvent;
              setDisplayedChatHistory(chatMessageEvent.value);
            }
            if (event.type === 'delta') {
              const chatMessageEvent = event as ChatMessageEvent;
              chatResponse += chatMessageEvent.value;
              setCurrentResponse(chatResponse);
            }
          });
      }
      setDisplayedChatHistory((chatHistory) => [
        ...chatHistory,
        {
          role: ChatItem.role.USER,
          content: currentPrompt,
          type: ChatItem.type.TEXT
        },
        {
          role: ChatItem.role.ASSISTANT,
          content: chatResponse,
          type: ChatItem.type.TEXT
        }
      ]);
      setCurrentPrompt('');
      setCurrentResponse('');
      setIsChatWaiting(false);
    }
  };

  // Scroll to the latest message when the chat history changes
  useEffect(() => {
    scrollToLatest();
  }, [displayedChatHistory, currentResponse, isChatWaiting]);

  if (isInitialLoading) {
    return <Loading />;
  }
  return (
    <div className="mr-4 bg-white  w-full flex flex-col h-full">
      <h1 className="text-2xl font-bold px-4 text-gray-600">{'Learn Burr '}</h1>
      <h2 className="text-lg font-normal px-4 text-gray-500 flex flex-row">
        The chatbot below is implemented using Burr. Watch the Burr UI (on the right) change as you
        chat...
      </h2>
      <div className="flex-1 overflow-y-auto p-4 hide-scrollbar" id={VIEW_END_ID}>
        {displayedChatHistory.map((message, i) => (
          <ChatMessage message={message} key={i} />
        ))}
        {isChatWaiting && (
          <ChatMessage
            message={{
              role: ChatItem.role.USER,
              content: currentPrompt,
              type: ChatItem.type.TEXT
            }}
          />
        )}
        {isChatWaiting && (
          <ChatMessage
            message={{
              content: currentResponse,
              type: ChatItem.type.TEXT,
              role: ChatItem.role.ASSISTANT
            }}
          />
        )}
      </div>
      <div className="flex items-center pt-4 gap-2">
        <input
          className="flex h-10 w-full rounded-md border border-[#e5e7eb] px-3 py-2 text-sm placeholder-[#6b7280] focus:outline-none focus:ring-2 focus:ring-[#9ca3af] disabled:cursor-not-allowed disabled:opacity-50 text-[#030712] focus-visible:ring-offset-2"
          placeholder="Ask me how tall the Eifel tower is!"
          value={currentPrompt}
          onChange={(e) => setCurrentPrompt(e.target.value)}
          onKeyDown={(e: KeyboardEvent<HTMLInputElement>) => {
            if (e.key === 'Enter' && !e.shiftKey) {
              e.preventDefault();
              submitPrompt();
            }
          }}
          disabled={isChatWaiting || props.appId === undefined}
        />
        <Button
          className="w-min cursor-pointer h-full"
          color="dark"
          disabled={isChatWaiting || props.appId === undefined}
          onClick={() => {
            submitPrompt();
          }}>
          Send
        </Button>
      </div>
    </div>
  );
};

export const StreamingChatbotWithTelemetry = () => {
  const currentProject = 'demo_streaming_chatbot';
  const [currentApp, setCurrentApp] = useState<ApplicationSummary | undefined>(undefined);

  return (
    <TwoColumnLayout
      firstItem={<StreamingChatbot projectId={currentProject} appId={currentApp?.app_id} />}
      secondItem={
        <TelemetryWithSelector
          projectId={currentProject}
          currentApp={currentApp}
          setCurrentApp={setCurrentApp}
          createNewApp={
            DefaultService.createNewApplicationApiV0StreamingChatbotCreateProjectIdAppIdPost
          }
        />
      }
      mode={'third'}></TwoColumnLayout>
  );
};
