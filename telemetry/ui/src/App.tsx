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

import { BrowserRouter as Router, Navigate, useRoutes } from 'react-router-dom';
import type { RouteObject } from 'react-router-dom';
import './App.css';
import { ProjectList } from './components/routes/ProjectList';
import { AppList } from './components/routes/AppList';
import { AppViewContainer } from './components/routes/app/AppView';
import { QueryClient, QueryClientProvider } from 'react-query';
import { AppContainer } from './components/nav/appcontainer';
import { ChatbotWithTelemetry } from './examples/Chatbot';
import { Counter } from './examples/Counter';
import { EmailAssistantWithTelemetry } from './examples/EmailAssistant';
import { StreamingChatbotWithTelemetry } from './examples/StreamingChatbot';
import { AdminView } from './components/routes/AdminView';
import { AnnotationsViewContainer } from './components/routes/app/AnnotationsView';
import { DeepResearcherWithTelemetry } from './examples/DeepResearcher';
import { useTheme } from './hooks/useTheme';

/**
 * Basic application. We have an AppContainer -- this has a breadcrumb and a sidebar.
 * We refer to route paths to gather parameters, as its simple to wire through. We may
 * want to consider passing parameters in to avoid overly coupled dependencies/ensure
 * more reusable top-level components.
 *
 * Note that you can run this in one of two modes:
 * 1. As an asset served by the backend
 * 2. Standalone, using npm run
 *
 * npm run will proxy to port 7241, versus the asset which will
 * hit the backend (on the same port/server as the FE, its just a static route).
 *
 * @returns A rendered application object
 */
export const appRoutes: RouteObject[] = [
  { id: 'root', path: '/', element: <Navigate to="/projects" /> },
  { id: 'projects', path: '/projects', element: <ProjectList /> },
  { id: 'project-apps-all', path: '/project/:projectId', element: <AppList /> },
  {
    id: 'identity-app-list',
    path: '/partition-identity/:projectId/apps',
    element: <AppList />
  },
  {
    id: 'identity-app-detail',
    path: '/partition-identity/:projectId/app/:appId',
    element: <AppViewContainer />
  },
  { id: 'legacy-app-list', path: '/project/:projectId/:partitionKey', element: <AppList /> },
  {
    id: 'legacy-app-detail',
    path: '/project/:projectId/:partitionKey/:appId',
    element: <AppViewContainer />
  },
  { id: 'annotations', path: '/annotations/:projectId/', element: <AnnotationsViewContainer /> },
  { id: 'demo-counter', path: '/demos/counter', element: <Counter /> },
  { id: 'demo-chatbot', path: '/demos/chatbot', element: <ChatbotWithTelemetry /> },
  {
    id: 'demo-streaming-chatbot',
    path: '/demos/streaming-chatbot',
    element: <StreamingChatbotWithTelemetry />
  },
  { id: 'demo-email', path: '/demos/email-assistant', element: <EmailAssistantWithTelemetry /> },
  {
    id: 'demo-deep-researcher',
    path: '/demos/deep-researcher',
    element: <DeepResearcherWithTelemetry />
  },
  { id: 'admin', path: '/admin', element: <AdminView /> },
  { id: 'fallback', path: '*', element: <Navigate to="/projects" /> }
];

const AppRoutes = () => useRoutes(appRoutes);

const App = () => {
  // Initialize theme at the app root so the `dark` class is applied on load
  // (respects system preference, falls back to stored manual override).
  useTheme();
  return (
    <QueryClientProvider client={new QueryClient()}>
      <Router basename={window.__BURR_BASE_PATH__ || ''}>
        <AppContainer>
          <AppRoutes />
        </AppContainer>
      </Router>
    </QueryClientProvider>
  );
};

export default App;
