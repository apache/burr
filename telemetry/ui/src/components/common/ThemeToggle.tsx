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

import { MoonIcon, SunIcon } from '@heroicons/react/24/outline';
import { classNames } from '../../utils/tailwind';
import { useTheme } from '../../hooks/useTheme';

/**
 * A simple sun/moon button that toggles between light and dark mode.
 * Replaces the previously broken radio toggle referenced in issue #209.
 */
export const ThemeToggle = (props: { showLabel?: boolean }) => {
  const { isDark, toggle } = useTheme();
  const Icon = isDark ? SunIcon : MoonIcon;
  const label = isDark ? 'Switch to light mode' : 'Switch to dark mode';
  return (
    <button
      type="button"
      onClick={toggle}
      title={label}
      aria-label={label}
      className={classNames(
        'group flex items-center gap-x-3 rounded-md p-2 text-sm leading-6 font-semibold',
        'text-gray-700 hover:bg-gray-50 hover:text-dwdarkblue',
        'dark:text-gray-200 dark:hover:bg-gray-800 dark:hover:text-white'
      )}>
      <Icon className="h-6 w-6 shrink-0 text-gray-400 group-hover:text-dwdarkblue dark:group-hover:text-white" />
      {props.showLabel && <span>{isDark ? 'Light mode' : 'Dark mode'}</span>}
    </button>
  );
};
