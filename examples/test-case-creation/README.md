<!--
     Licensed to the Apache Software Foundation (ASF) under one
     or more contributor license agreements.  See the NOTICE file
     distributed with this work for additional information
     regarding copyright ownership.  The ASF licenses this file
     to you under the Apache License, Version 2.0 (the
     "License"); you may not use this file except in compliance
     with the License.  You may obtain a copy of the License at

       http://www.apache.org/licenses/LICENSE-2.0

     Unless required by applicable law or agreed to in writing,
     software distributed under the License is distributed on an
     "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
     KIND, either express or implied.  See the License for the
     specific language governing permissions and limitations
     under the License.
-->

# Creating robust applications by creating test cases
This example shows you how you can easily create (integration) test cases for Burr your project.

With Burr it is easy to foster a test-driven development mindset when developing actions, which are the building blocks of your Burr
application.

Note: writing test cases for GenAI projects can be tricky. The same LLM API calls
can result in different outputs. This means that 'exact' equality tests may not work,
and you'll need to resort to more fuzzy tests like checking for the presence of certain
words or phrases, or using LLMs to grade the output, etc. We aren't opinionated on how you
do this, but in any case, you'll need to write a test case to exercise things, and this
is what we're showing you how to do here.


## Motivation

With LLMs non-deterministic behavior can impact your application's behavior. It is important to create test cases to
ensure that your application is robust and behaves as expected; it is easy to tweak a prompt and break
a particular use case. This example shows you how you can create test cases
for your project from real traces, since part of the struggle is to create test cases that are representative of the
real-world behavior of your application -- Burr can make this process easier.

## Steps
1. Build your project with Burr.
2. Run your Burr application with tracking/persistence.
3. Find a trace that you want to create a test case for.
4. Note the partition_key, app_id, and sequence_id of the trace. You can find these in the UI.
5. Create a test case using the `burr-test-case create` command passing the project name, partition_key, app_id, and sequence_id as arguments.
6. Choose what you're going to test and how. E.g. exact match, similarity, LLM Grader, etc.
7. Iterate on the test case until it is robust and representative of the real-world behavior of your application.
8. Profit.

For step (5) above, this is the corresponding command:
```bash
%%sh
burr-test-case create  \
  --project-name "SOME_NAME" \
  --partition-key "SOME_KEY" \
  --app-id "SOME_ID" \
  --sequence-id 0 \
  --target-file-name /tmp/test-case.json
```
See [the notebook](./notebook.ipynb) for example usage.

## Testing Actions
In `test_application.py` you'll find examples tests for a simple action
that is found in `application.py`.

## Notebook
The notebook also shows how things work. <a target="_blank" href="https://colab.research.google.com/github/apache/burr/blob/main/examples/test-case-creation/notebook.ipynb">
  <img src="https://colab.research.google.com/assets/colab-badge.svg" alt="Open In Colab"/>
</a>

## Future Work
We see many more improvements here:

1. Annotating data in the UI to make it easier to pull out.
2. Automatically suggesting tests cases for you to add.
3. Data export / integration with evaluation tools.
4. etc. Please let us know what you need!
