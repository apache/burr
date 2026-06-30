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

import { useCallback, useEffect, useState } from 'react';

export type ThemePreference = 'light' | 'dark' | 'system';

const STORAGE_KEY = 'burr-theme';

const getSystemPrefersDark = (): boolean =>
  typeof window !== 'undefined' &&
  window.matchMedia &&
  window.matchMedia('(prefers-color-scheme: dark)').matches;

const getStoredPreference = (): ThemePreference => {
  if (typeof window === 'undefined') {
    return 'system';
  }
  const stored = window.localStorage.getItem(STORAGE_KEY);
  if (stored === 'light' || stored === 'dark' || stored === 'system') {
    return stored;
  }
  return 'system';
};

/**
 * Applies (or removes) the `dark` class on the root <html> element based on the
 * resolved theme. Tailwind is configured with darkMode: 'class', so this is what
 * actually switches the styling.
 */
const applyDarkClass = (isDark: boolean) => {
  const root = document.documentElement;
  if (isDark) {
    root.classList.add('dark');
  } else {
    root.classList.remove('dark');
  }
};

/**
 * Theme hook that respects system preference by default, allows a manual
 * override, and persists the choice to localStorage.
 *
 * - `preference` is the user's stored choice ('light' | 'dark' | 'system').
 * - `isDark` is the resolved value actually applied to the DOM.
 * - `setPreference` updates and persists the choice.
 * - `toggle` cycles between light and dark (collapsing 'system' to its resolved value first).
 */
export const useTheme = () => {
  const [preference, setPreferenceState] = useState<ThemePreference>(getStoredPreference);
  const [systemPrefersDark, setSystemPrefersDark] = useState<boolean>(getSystemPrefersDark);

  // Keep track of the system preference so 'system' mode reacts to OS changes.
  useEffect(() => {
    if (!window.matchMedia) {
      return;
    }
    const mediaQuery = window.matchMedia('(prefers-color-scheme: dark)');
    const handler = (event: MediaQueryListEvent) => setSystemPrefersDark(event.matches);
    mediaQuery.addEventListener('change', handler);
    return () => mediaQuery.removeEventListener('change', handler);
  }, []);

  const isDark = preference === 'system' ? systemPrefersDark : preference === 'dark';

  // Apply the resolved theme to the DOM whenever it changes.
  useEffect(() => {
    applyDarkClass(isDark);
  }, [isDark]);

  const setPreference = useCallback((next: ThemePreference) => {
    setPreferenceState(next);
    if (next === 'system') {
      window.localStorage.removeItem(STORAGE_KEY);
    } else {
      window.localStorage.setItem(STORAGE_KEY, next);
    }
  }, []);

  const toggle = useCallback(() => {
    setPreference(isDark ? 'light' : 'dark');
  }, [isDark, setPreference]);

  return { preference, isDark, setPreference, toggle };
};
