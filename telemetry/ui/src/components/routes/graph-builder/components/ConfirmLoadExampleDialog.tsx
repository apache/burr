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

import React from 'react';
import { Button } from '../../../common/button';
import { ExclamationTriangleIcon } from '@heroicons/react/24/outline';

interface ConfirmLoadExampleDialogProps {
  open: boolean;
  onClose: () => void;
  onConfirm: () => void;
  exampleTitle: string;
  hasExistingContent: boolean;
}

const ConfirmLoadExampleDialog: React.FC<ConfirmLoadExampleDialogProps> = ({
  open,
  onClose,
  onConfirm,
  exampleTitle,
  hasExistingContent
}) => {
  if (!open) return null;

  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
      <div className="bg-white rounded-lg p-6 w-full max-w-md mx-4">
        <div className="flex items-center gap-2 mb-4">
          <ExclamationTriangleIcon className="w-6 h-6 text-amber-500" />
          <h2 className="text-lg font-semibold">Load Example Graph</h2>
        </div>

        <div className="space-y-4">
          <p className="text-gray-700">
            Are you sure you want to load the &quot;{exampleTitle}&quot; example?
          </p>

          {hasExistingContent && (
            <div className="bg-amber-50 border border-amber-200 rounded-md p-3">
              <p className="text-sm text-amber-800">
                This will replace your current graph. Any unsaved changes will be lost.
              </p>
            </div>
          )}

          <div className="text-sm text-gray-500">
            You can always export your current work as JSON or Python code before loading the
            example.
          </div>
        </div>

        <div className="flex justify-end space-x-2 mt-6">
          <Button onClick={onClose} outline>
            Cancel
          </Button>
          <Button onClick={onConfirm} color={hasExistingContent ? 'amber' : 'blue'}>
            {hasExistingContent ? 'Replace Graph' : 'Load Example'}
          </Button>
        </div>
      </div>
    </div>
  );
};

export default ConfirmLoadExampleDialog;
