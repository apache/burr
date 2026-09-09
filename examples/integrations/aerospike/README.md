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

# Aerospike + Burr

This example extends the Burr simple chatbot with durable state in Aerospike. The persister saves one immutable checkpoint after every action and reloads the latest checkpoint when an application with the same identifiers starts again.

## Install dependencies

Python 3.10 or newer is required for the Aerospike integration.

```bash
pip install "apache-burr[aerospike]" openai
```

When running from this repository, install the checkout into its virtual environment instead:

```bash
uv pip install --python .venv/bin/python -e ".[aerospike]" openai
```

## Start Aerospike

Start a local Aerospike Community Edition database with Docker:

```bash
docker run --name burr-aerospike -d \
  -p 3000:3000 \
  aerospike/aerospike-server
```

The example uses the default `test` namespace. Aerospike creates the `burr_state` and `burr_head` sets on the first write.

## Run the chatbot

Set `OPENAI_API_KEY`, then run:

```bash
export OPENAI_API_KEY="your-key"
python aerospike_local.py
```

From the repository root with the existing virtual environment:

```bash
export OPENAI_API_KEY="your-key"
.venv/bin/python examples/integrations/aerospike/aerospike_local.py
```

Enter `exit` or `quit` to stop. Restarting with the same `app_id` and `partition_key` restores the conversation from Aerospike.

Use command-line options to select a conversation or send one prompt:

```bash
python aerospike_local.py \
  --app-id another-conversation \
  --partition-key another-user \
  --prompt "What did we discuss last time?"
```

The example keeps at most 20 chat messages in the current state. The Aerospike persister still retains an immutable checkpoint for every completed Burr action.

## Inspect persisted checkpoints

Run AQL from the Aerospike tools image on the server container's network:

```bash
docker run --rm -it \
  --network container:burr-aerospike \
  aerospike/aerospike-tools \
  aql -h 127.0.0.1
```

At the AQL prompt, list the sets and inspect the saved checkpoints:

```sql
SHOW SETS
SELECT * FROM test.burr_state
```

Each `burr_state` record is an immutable checkpoint. The relevant bins include:

- `app_id`: conversation identifier, `aerospike-chatbot` by default
- `sequence_id`: action sequence number
- `position`: action that produced the checkpoint
- `state`: serialized Burr state, including the chat history
- `status`: action completion status

The mutable record that points to the latest checkpoint for each conversation is stored separately:

```sql
SELECT * FROM test.burr_head
```

You can also execute a query without opening an interactive AQL prompt:

```bash
docker run --rm \
  --network container:burr-aerospike \
  aerospike/aerospike-tools \
  aql -h 127.0.0.1 -c "SELECT * FROM test.burr_state"
```

