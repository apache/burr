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

import { Fragment, useState } from 'react';
import { Dialog, Disclosure, Transition } from '@headlessui/react';
import {
  ComputerDesktopIcon,
  Square2StackIcon,
  QuestionMarkCircleIcon,
  XMarkIcon,
  ChatBubbleLeftEllipsisIcon,
  ChevronLeftIcon,
  ChevronRightIcon,
  ChevronDownIcon,
  FolderIcon
} from '@heroicons/react/24/outline';
import { ListBulletIcon } from '@heroicons/react/20/solid';
import { BreadCrumb } from './breadcrumb';
import { Link } from 'react-router-dom';
import { classNames } from '../../utils/tailwind';
import React from 'react';
import { DefaultService } from '../../api';
import { useQuery } from 'react-query';

// Define your GitHub logo SVG as a React component
const GithubLogo = () => (
  <svg
    style={{ width: 20 }}
    xmlns="http://www.w3.org/2000/svg"
    fill="none"
    viewBox="0 0 22 22"
    stroke="currentColor"
  >
    {/* SVG path for GitHub logo */}
    <path
      strokeLinecap="round"
      strokeLinejoin="round"
      strokeWidth={0.5}
      d="M12 2C6.477 2 2 6.477 2 12c0 4.418 2.865 8.166 6.839 9.489.5.09.682-.217.682-.482 0-.237-.009-.868-.014-1.703-2.782.6-3.369-1.34-3.369-1.34-.454-1.156-1.11-1.462-1.11-1.462-.908-.62.069-.608.069-.608 1.004.07 1.532 1.03 1.532 1.03.892 1.529 2.341 1.088 2.91.833.091-.646.349-1.086.635-1.337-2.22-.25-4.555-1.11-4.555-4.943 0-1.091.39-1.984 1.03-2.682-.103-.251-.447-1.265.098-2.634 0 0 .84-.27 2.75 1.02A9.564 9.564 0 0112 7.07c.85.004 1.705.115 2.502.337 1.909-1.29 2.747-1.02 2.747-1.02.547 1.37.203 2.383.1 2.634.64.698 1.028 1.59 1.028 2.682 0 3.842-2.337 4.687-4.565 4.932.359.31.678.92.678 1.852 0 1.335-.012 2.415-.012 2.741 0 .267.18.576.688.479C19.137 20.164 22 16.416 22 12c0-5.523-4.477-10-10-10z"
    />
  </svg>
);

/**
 * Toggles the sidebar open and closed.
 */
const ToggleOpenButton = (props: { open: boolean; toggleSidebar: () => void }) => {
  const MinimizeMaximizeIcon = props.open ? ChevronLeftIcon : ChevronRightIcon;
  return (
    <MinimizeMaximizeIcon
      className={classNames(
        'text-gray-400',
        'h-8 w-8 hover:bg-gray-50 rounded-md hover:cursor-pointer'
      )}
      aria-hidden="true"
      onClick={props.toggleSidebar}
    />
  );
};

/**
 * Container for the app. Contains three main parts:
 * 1. The sidebar
 * 2. The breadcrumb
 * 3. The main content
 *
 * TODO -- get this to work in small mode -- the sidebar is currently not there.
 */
export const AppContainer = (props: { children: React.ReactNode }) => {
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [smallSidebarOpen, setSmallSidebarOpen] = useState(false);
  const { data: backendSpec } = useQuery(['backendSpec'], () =>
    DefaultService.getAppSpecApiV0MetadataAppSpecGet().then((response) => {
      return response;
    })
  );
  const toggleSidebar = () => {
    setSidebarOpen(!sidebarOpen);
  };
  const navigation = [
    {
      name: 'Projects',
      href: '/projects',
      icon: Square2StackIcon,
      linkType: 'internal'
    },
    {
      name: 'Examples',
      href: 'https://github.com/DAGWorks-Inc/burr/tree/main/examples',
      icon: FolderIcon,
      linkType: 'external'
    },
    ...(backendSpec?.supports_demos
      ? [
          {
            name: 'Demos',
            href: '/demos',
            icon: ListBulletIcon,
            linkType: 'internal',
            children: [
              { name: 'counter', href: '/demos/counter', current: false, linkType: 'internal' },
              { name: 'chatbot', href: '/demos/chatbot', current: false, linkType: 'internal' },
              {
                name: 'email-assistant',
                href: '/demos/email-assistant',
                current: false,
                linkType: 'internal'
              },
              {
                name: 'streaming-chatbot',
                href: '/demos/streaming-chatbot',
                current: false,
                linkType: 'internal'
              },
              {
                name: 'deep-researcher',
                href: '/demos/deep-researcher',
                current: false,
                linkType: 'internal'
              }
            ]
          }
        ]
      : []),
    {
      name: 'Develop',
      href: 'https://github.com/dagworks-inc/burr',
      icon: ComputerDesktopIcon,
      linkType: 'external'
    },
    {
      name: 'Documentation',
      href: 'https://burr.apache.org',
      icon: QuestionMarkCircleIcon,
      linkType: 'external'
    },
    {
      name: 'GitHub Discussions',
      href: 'https://github.com/apache/burr/discussions',
      icon: GithubLogo,
      linkType: 'external'
    },
    {
      name: 'Get Help on Discord',
      href: 'https://discord.gg/emUEvxTb4D',
      icon: ChatBubbleLeftEllipsisIcon,
      linkType: 'external'
    }
  ];

  if (backendSpec?.indexing) {
    navigation.push({
      name: 'Admin',
      href: '/admin',
      icon: ListBulletIcon,
      linkType: 'internal'
    });
  }

  const isCurrent = (href: string, linkType: string) => {
    if (linkType === 'external') {
      return false;
    }
    return window.location.pathname.startsWith(href);
  };

  return (
    <>
      <div className="h-screen w-screen overflow-x-auto">
        <Transition.Root show={smallSidebarOpen} as={Fragment}>
          <Dialog as="div" className="relative z-50 lg:hidden" onClose={setSmallSidebarOpen}>
            <Transition.Child
              as={Fragment}
              enter="transition-opacity ease-linear duration-300"
              enterFrom="opacity-0"
              enterTo="opacity-100"
              leave="transition-opacity ease-linear duration-300"
              leaveFrom="opacity-100"
              leaveTo="opacity-0"
            >
              <div className="fixed inset-0 bg-gray-900/80" />
            </Transition.Child>

            <div className="fixed inset-0 flex">
              <Transition.Child
                as={Fragment}
                enter="transition ease-in-out duration-300 transform"
                enterFrom="-translate-x-full"
                enterTo="translate-x-0"
                leave="transition ease-in-out duration-300 transform"
                leaveFrom="translate-x-0"
                leaveTo="-translate-x-full"
              >
                <Dialog.Panel className="relative mr-16 flex w-full max-w-xs flex-1">
                  <Transition.Child
                    as={Fragment}
                    enter="ease-in-out duration-300"
                    enterFrom="opacity-0"
                    enterTo="opacity-100"
                    leave="ease-in-out duration-300"
                    leaveFrom="opacity-100"
                    leaveTo="opacity-0"
                  >
                    <div className="absolute left-full top-0 flex w-16 justify-center pt-5">
                      <button
                        type="button"
                        className="-m-2.5 p-2.5"
                        onClick={() => setSmallSidebarOpen(false)}
                      >
                        <span className="sr-only">Close sidebar</span>
                        <XMarkIcon className="h-6 w-6 text-white" aria-hidden="true" />
                      </button>
                    </div>
                  </Transition.Child>
                  {/* Sidebar component, swap this element with another sidebar if you like */}
                  <div className="flex grow flex-col gap-y-5 overflow-y-auto bg-white px-6 pb-2 py-2">
                    <div className="flex h-16 shrink-0 items-center">
                      <img className="h-10 w-auto" src={'/logo.png'} alt="Burr" />
                    </div>
                    <nav className="flex flex-1 flex-col">
                      <ul role="list" className="flex flex-1 flex-col gap-y-7">
                        <li>
                          <ul role="list" className="-mx-2 space-y-1">
                            {navigation.map((item) => (
                              <li key={item.name}>
                                <Link
                                  to={item.href}
                                  className={classNames(
                                    isCurrent(item.href, item.linkType)
                                      ? 'bg-gray-50 text-dwdarkblue'
                                      : item.linkType === 'external'
                                        ? 'text-gray-700 hover:text-dwdarkblue'
                                        : 'text-gray-700 hover:text-dwdarkblue hover:bg-gray-50',
                                    'group flex gap-x-3 rounded-md p-2 text-sm leading-6 font-semibold'
                                  )}
                                  target={item.linkType === 'external' ? '_blank' : undefined}
                                  rel={item.linkType === 'external' ? 'noreferrer' : undefined}
                                >
                                  <item.icon
                                    className={classNames(
                                      isCurrent(item.href, item.linkType)
                                        ? 'text-dwdarkblue'
                                        : 'text-gray-400 group-hover:text-dwdarkblue',
                                      'h-6 w-6 shrink-0'
                                    )}
                                    aria-hidden="true"
                                  />
                                  {item.name}
                                </Link>
                              </li>
                            ))}
                          </ul>
                        </li>
                      </ul>
                    </nav>
                  </div>
                </Dialog.Panel>
              </Transition.Child>
            </div>
          </Dialog>
        </Transition.Root>

        {/* Static sidebar for desktop */}
        <div
          className={`hidden ${
            sidebarOpen ? 'h-screen lg:fixed lg:inset-y-0 lg:z-50 lg:flex lg:w-72 lg:flex-col' : ''
          }`}
        >
          {/* Sidebar component, swap this element with another sidebar if you like */}
          <div className="flex grow flex-col gap-y-5 overflow-y-auto border-r border-gray-200 bg-white px-6 py-2">
            <div className="flex h-16 shrink-0 items-center">
              <img className="h-12 w-auto" src={'/public/logo.png'} alt="Burr" />
            </div>
            <nav className="flex flex-1 flex-col">
              <ul role="list" className="flex flex-1 flex-col gap-y-7">
                <li>
                  <ul role="list" className="-mx-2 space-y-1">
                    {navigation.map((item) => (
                      <li key={item.name}>
                        {!item?.children ? (
                          <Link
                            to={item.href}
                            className={classNames(
                              isCurrent(item.href, item.linkType)
                                ? 'bg-gray-50'
                                : 'hover:bg-gray-50',
                              'group flex gap-x-3 rounded-md p-2 text-sm leading-6 font-semibold text-gray-700'
                            )}
                            target={item.linkType === 'external' ? '_blank' : undefined}
                            rel={item.linkType === 'external' ? 'noreferrer' : undefined}
                          >
                            <item.icon
                              className="h-6 w-6 shrink-0 text-gray-400"
                              aria-hidden="true"
                            />
                            {item.name}
                          </Link>
                        ) : (
                          <Disclosure as="div">
                            {({ open }) => (
                              <>
                                <Disclosure.Button
                                  className={classNames(
                                    isCurrent(item.href, item.linkType)
                                      ? 'bg-gray-50'
                                      : 'hover:bg-gray-50',
                                    'flex items-center w-full text-left rounded-md p-2 gap-x-3 text-sm leading-6 font-semibold text-gray-700'
                                  )}
                                >
                                  <item.icon
                                    className="h-6 w-6 shrink-0 text-gray-400"
                                    aria-hidden="true"
                                  />
                                  {item.name}
                                  <ChevronDownIcon
                                    className={classNames(
                                      open ? 'rotate-180 text-gray-500' : 'text-gray-400',
                                      'ml-auto h-5 w-5 shrink-0'
                                    )}
                                    aria-hidden="true"
                                  />
                                </Disclosure.Button>
                                <Disclosure.Panel as="ul" className="mt-1 px-2">
                                  {item.children.map((subItem) => (
                                    <li key={subItem.name}>
                                      <Link
                                        to={subItem.href}
                                        className={classNames(
                                          isCurrent(subItem.href, subItem.linkType)
                                            ? 'bg-gray-50'
                                            : 'hover:bg-gray-50',
                                          'block rounded-md py-2 pr-2 pl-9 text-sm leading-6 text-gray-700'
                                        )}
                                        target={
                                          subItem.linkType === 'external' ? '_blank' : undefined
                                        }
                                        rel={
                                          subItem.linkType === 'external' ? 'noreferrer' : undefined
                                        }
                                      >
                                        {subItem.name}
                                      </Link>
                                    </li>
                                  ))}
                                </Disclosure.Panel>
                              </>
                            )}
                          </Disclosure>
                        )}
                      </li>
                    ))}
                  </ul>
                </li>
              </ul>
            </nav>
            <div className="flex justify-start -mx-5">
              <ToggleOpenButton open={sidebarOpen} toggleSidebar={toggleSidebar} />
            </div>
          </div>
        </div>
        <div
          className={`hidden h-screen ${
            !sidebarOpen
              ? 'lg:fixed lg:inset-y-0 lg:z-50 lg:flex lg:w-8 lg:flex-col justify-end lg:py-2 lg:px-1'
              : ''
          }`}
        >
          <ToggleOpenButton open={sidebarOpen} toggleSidebar={toggleSidebar} />
        </div>

        {/* This is a bit hacky -- just quickly prototyping and these margins were the ones that worked! */}
        <main className={`py-14 -my-1 ${sidebarOpen ? 'lg:pl-72' : 'lg:pl-5'} h-full`}>
          <div className="flex items-center px-5 sm:px-7 lg:px-9 pb-8 -my-4">
            <BreadCrumb />
          </div>
          <div className="flex h-full flex-col">
            <div className="px-4 sm:px-6 lg:px-2 max-h-full h-full flex-1"> {props.children}</div>
          </div>
        </main>
      </div>
    </>
  );
};
