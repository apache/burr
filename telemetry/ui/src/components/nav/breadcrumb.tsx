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

import { HomeIcon } from '@heroicons/react/20/solid';
import { Link, useLocation } from 'react-router-dom';

/**
 * Breadcrumb component
 * This isn't perfect as not all the sub-routes map to a name
 * (and you can click on any of them), but it works for now,
 * and no routes lead to nothing (the /project route leads
 * to /projects, which is the default...)
 */
export const BreadCrumb = () => {
  const location = useLocation();
  const pathnames = location.pathname.split('/').filter((x) => x);

  const pages = pathnames.map((value, index) => {
    const href = `/${pathnames.slice(0, index + 1).join('/')}`;
    const isCurrentPage = index === pathnames.length - 1;
    return {
      name: value,
      href,
      current: isCurrentPage
    };
  });
  {
    return (
      <nav className="flex" aria-label="Breadcrumb">
        <ol role="list" className="flex items-center space-x-4">
          <li>
            <div>
              <Link to="/" className="text-gray-400 hover:text-gray-500">
                <HomeIcon className="h-5 w-5 flex-shrink-0" aria-hidden="true" />
                <span className="sr-only">Home</span>
              </Link>
            </div>
          </li>
          {pages.map((page, index) => {
            // Quick trick to catch null primary keys
            const isNullPK = page.name === 'null' && index === 2;
            return (
              <li key={page.name}>
                <div className="flex items-center">
                  <svg
                    className="h-5 w-5 flex-shrink-0 text-gray-300"
                    fill="currentColor"
                    viewBox="0 0 20 20"
                    aria-hidden="true"
                  >
                    <path d="M5.555 17.776l8-16 .894.448-8 16-.894-.448z" />
                  </svg>
                  {isNullPK ? (
                    <span className="ml-4 text-sm font-medium text-gray-200 dark:text-gray-600">
                      no primary key
                    </span>
                  ) : (
                    <Link
                      to={page.href}
                      className="ml-4 text-sm font-medium text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-200"
                      aria-current={page.current ? 'page' : undefined}
                    >
                      {decodeURIComponent(page.name)}
                    </Link>
                  )}
                </div>
              </li>
            );
          })}
        </ol>
      </nav>
    );
  }
};
