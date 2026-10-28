<!--
     Licensed to the Apache Software Foundation (ASF) under one
     or more contributor license agreements. See the NOTICE file
     distributed with this work for additional information
     regarding copyright ownership. The ASF licenses this file
     to you under the Apache License, Version 2.0 (the
     "License"); you may not use this file except in compliance
     with the License. You may obtain a copy of the License at

       http://www.apache.org/licenses/LICENSE-2.0

     Unless required by applicable law or agreed to in writing,
     software distributed under the License is distributed on an
     "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
     KIND, either express or implied. See the License for the
     specific language governing permissions and limitations
     under the License.
-->

# Deploy Burr to Cloudflare Workers

This example deploys the same counter application as the
[Vercel example](../vercel/) using Cloudflare's Python Workers runtime.
`POST /api/counter` runs the Burr application and returns its serialized State.

## Prerequisites

- Node.js 22 or later, Python 3.13 or later, and [uv](https://docs.astral.sh/uv/).
- A Cloudflare account for deployment. Local testing needs no account.

## Local setup

From this directory:

```bash
npm install --package-lock=false
uv run pywrangler dev
```

`pywrangler` installs the Python dependencies and starts the local Worker at
`http://localhost:8787`. Direct dependency versions are specified in
`package.json` and `pyproject.toml`; generated lock files are ignored by Git.

In another terminal, test the counter:

```bash
curl -X POST http://localhost:8787/api/counter \
  -H 'Content-Type: application/json' \
  -d '{"number": 5}'
```

Expected response:

```json
{"counter": 5, "counter_limit": 5, "__SEQUENCE_ID": 5, "__PRIOR_STEP": "result"}
```

Each request starts a new counter. Requests with a missing, invalid or
nonpositive `number` return HTTP 400; other HTTP methods return HTTP 405.

## Deploy

Log in to Cloudflare:

```bash
npx wrangler login
```

Choose a Worker name in `wrangler.jsonc`, then deploy:

```bash
uv run pywrangler deploy
```

Use the HTTPS URL printed by Wrangler to test the deployed Worker:

```bash
curl -X POST https://your-worker.your-subdomain.workers.dev/api/counter \
  -H 'Content-Type: application/json' \
  -d '{"number": 5}'
```

The response should match the local result above.

## Troubleshooting

- For HTTP 404, check that the request path is `/api/counter`.
- For HTTP 405, send a POST request with the JSON body shown above.
- To inspect deployed Worker logs, run `npx wrangler tail`.

## Resources

- [Cloudflare Python Workers](https://developers.cloudflare.com/workers/languages/python/)
- [Python package support](https://developers.cloudflare.com/workers/languages/python/packages/)
- [Wrangler commands](https://developers.cloudflare.com/workers/wrangler/commands/)
