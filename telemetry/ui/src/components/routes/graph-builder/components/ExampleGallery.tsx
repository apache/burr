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
import { PlayIcon } from '@heroicons/react/24/outline';
import { Button } from '../../../common/button';
import { ExampleGraph } from '../data/examples';

interface ExampleGalleryProps {
  examples: ExampleGraph[];
  onLoadExample: (example: ExampleGraph) => void;
}

const ExampleGallery: React.FC<ExampleGalleryProps> = ({ examples, onLoadExample }) => {
  return (
    <div className="mt-6 pt-4 border-t border-gray-200">
      <h3 className="text-lg font-semibold text-gray-900 mb-1">Example Graphs</h3>
      <p className="text-sm text-gray-600 mb-4">
        Load pre-built examples to explore the graph builder
      </p>

      {examples.map((example) => (
        <div
          key={example.id}
          className="mb-4 border border-gray-200 rounded-lg hover:shadow-md hover:-translate-y-0.5 transition-all duration-200 ease-in-out"
        >
          <div className="p-4 pb-2">
            <h4 className="text-base font-medium text-gray-900 mb-2">{example.title}</h4>
            <p className="text-sm text-gray-600 mb-3">{example.description}</p>
            <div className="flex gap-2 mb-2">
              <span className="inline-flex items-center px-2 py-1 rounded text-xs border border-gray-300 bg-gray-50 text-gray-700">
                {example.nodes.length} nodes
              </span>
              <span className="inline-flex items-center px-2 py-1 rounded text-xs border border-gray-300 bg-gray-50 text-gray-700">
                {example.edges.length} edges
              </span>
            </div>
          </div>
          <div className="px-4 pb-4 pt-0 flex gap-2">
            <Button onClick={() => onLoadExample(example)} className="text-xs cursor-pointer">
              <PlayIcon className="w-3 h-3 mr-1" />
              Load Example
            </Button>
          </div>
        </div>
      ))}

      {examples.length === 0 && (
        <p className="text-sm text-gray-500 italic">No examples available yet.</p>
      )}
    </div>
  );
};

export default ExampleGallery;
