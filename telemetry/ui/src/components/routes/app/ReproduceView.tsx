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

import { ClipboardIcon } from '@heroicons/react/24/outline';
import { Step } from '../../../api';
import { useEffect, useState } from 'react';

const FlashMessage = ({
  message,
  duration,
  onClose
}: {
  message: string;
  duration: number;
  onClose: () => void;
}) => {
  useEffect(() => {
    const timer = setTimeout(onClose, duration);
    return () => clearTimeout(timer);
  }, [duration, onClose]);

  return (
    <div className="fixed bottom-4 right-4 bg-dwlightblue text-white p-2 rounded shadow-lg">
      {message}
    </div>
  );
};

export const ReproduceView = (props: {
  step: Step | undefined;
  appId: string;
  partitionKey: string;
  projectID: string;
}) => {
  const cmd =
    'burr-test-case create  \\\n' +
    `  --project-name "${props.projectID}" \\\n` +
    `  --partition-key "${props.partitionKey}" \\\n` +
    `  --app-id "${props.appId}" \\\n` +
    `  --sequence-id ${props.step ? props.step.step_start_log.sequence_id : '?'} \\\n` +
    '  --target-file-name YOUR_FIXTURE_FILE.json \n';

  const [isFlashVisible, setIsFlashVisible] = useState(false);

  return (
    <div className="pt-2 flex flex-col gap-4">
      {isFlashVisible && (
        <FlashMessage
          message="Copied to clipboard!"
          duration={2000}
          onClose={() => setIsFlashVisible(false)}
        />
      )}
      <div className="flex flex-row justify-between text-gray-700">
        <p>
          To generate a test case for this step, run the following command.
          <a
            href="https://burr.apache.org/examples/guardrails/creating_tests/"
            target="_blank"
            rel="noreferrer"
            className="hover:underline text-dwlightblue"
          >
            {' '}
            Further reading
          </a>
          .
        </p>{' '}
        <ClipboardIcon
          className="h-5 w-5 min-h-5 min-w-5 cursor-pointer hover:scale-110"
          onClick={() => {
            navigator.clipboard.writeText(cmd);
            setIsFlashVisible(true);
          }}
        />
      </div>
      <pre className="text-white bg-gray-800 p-2 rounded-md text-sm">{cmd}</pre>
    </div>
  );
};
