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

# Security Policy

Apache Burr is an incubating project at the Apache Software Foundation (ASF).
Vulnerabilities are handled under the [ASF security process](https://www.apache.org/security/).

## Reporting a vulnerability

Report suspected vulnerabilities **privately**, by plain-text email, to
[security@apache.org](mailto:security@apache.org). Do not open a GitHub issue,
pull request, or discussion, and do not post to the `dev@burr.apache.org` list.
Send one email per issue and include the affected version, a minimal
reproduction, and the impact you believe it has.

The ASF Security Team acknowledges the report and routes it to the Burr PPMC,
which works with the reporter privately until a fix is released and the issue
is announced. The full process, including CVE assignment, is described at
<https://apache.org/security/committers.html>.

Non-vulnerability questions (configuration, whether a release is affected by a
published CVE) belong on the dev list or GitHub Discussions.

## Supported versions

Burr is published to PyPI as [`apache-burr`](https://pypi.org/project/apache-burr/).
Security fixes are released as a new version in the latest minor release line
only. Older releases do not receive fixes; upgrade to the current release.

## Security model

This section states which parties Burr trusts and what it guarantees, so you
can tell a Burr vulnerability from a deployment concern. A report that
contradicts a guarantee below is in scope; one that assumes a trusted party is
hostile is not.

### Persisted state

The persistence store is inside the operator's trust boundary. A principal with
write access to persisted State, whether in the built-in SQLite persister or any
`burr.integrations.persisters` backend (PostgreSQL, MongoDB, Redis, and others),
is trusted to the same degree as the application that loads it. Burr does not
sign or integrity-bind persisted State, and its deserializers act on it as
operator-owned data.

### Expressions

`Condition.expr()` evaluates a developer-authored Python expression with `eval`
and must never receive text from an untrusted source. `Condition.safe_expr()`
is the API for less-trusted expressions (configuration files, rule editors,
end-user input). It validates the expression against a small allowlisted
grammar, interprets the tree directly without `eval`, and rejects anything
outside that grammar before the condition is constructed. `safe_expr()`
guarantees that no arbitrary code is executed and is designed to bound resource
use. A report that `safe_expr()` executes code it should not is in scope.

### Serialization

The serde integrations deserialize data read from the persistence store, so
they inherit the trust boundary above. The pydantic integration resolves class
names recorded at serialization time; the pandas integration reads parquet
files from paths recorded in State. The pickle serializer
(`burr.integrations.serde.pickle`) is opt-in and carries pickle's own
requirement: unpickling data is equivalent to running it. Do not enable it on
State that an untrusted party could write.

### Tracking server

The tracking server (`burr` CLI, `burr.tracking.server`) is a local development
tool, not a hardened multi-tenant service. It has no authentication or
authorization: anyone who can reach it can read the data exposed by its
configured backend and can write annotations. Some distributions also include
writable example application routes; these are demonstrations, not protected
application endpoints.

The CLI binds to `127.0.0.1` by default. Do not expose the server on another
network interface unless an authenticating reverse proxy or an equivalent
access-control layer protects it. Treat every caller that can reach an
unprotected server as trusted.

For the local filesystem backend, project and application identifiers received
by the tracking API are each treated as a single path component and validated
before use. A remote caller who can escape the configured storage root through
a crafted API identifier has crossed a Burr security boundary. The storage
root itself remains trusted, operator-controlled application data: Burr does
not defend against a local principal who can modify its files, replace them
with symlinks, or otherwise alter the directory layout.

### Identifiers

Project names, `app_id`, and `partition_key` are developer-supplied identifiers
used by tracking clients and persisters as directory names, object keys, or
record selectors, depending on the backend. Burr validates filesystem-bound
project and application identifiers as defense in depth. Applications remain
responsible for validating and authorizing identifiers derived from end-user
input; Burr's syntactic validation does not establish identity, ownership, or
access control.

Built-in example routes may use storage and configuration separate from the
tracking backend selected for the server. Do not assume that configuring a
backend also configures or secures those example applications.

### Dependencies

Burr does not vendor third-party code. Vulnerabilities in dependencies
(FastAPI, pydantic, database drivers, the UI's JavaScript components) should be
reported upstream; Burr picks up fixes through normal dependency updates.
Third-party components bundled into the UI in the wheel are listed in
[`LICENSE-wheel`](LICENSE-wheel).

## Out of scope

The following are not Burr vulnerabilities:

- Attacks that require write access to the persistence store, including crafted
  State deserialized by the pydantic, pandas, or pickle integrations.
- Passing untrusted text to `Condition.expr()`.
- Reading or changing tracking data through an intentionally exposed,
  unauthenticated tracking server, including its built-in example routes.
- Attacks that require local write access to the tracking storage root, such as
  replacing tracking files with symlinks. That directory is trusted and must be
  writable only by the Burr application identity.
- Crafted pickle payloads supplied to the opt-in pickle serializer.
- Denial of service through developer-authored code: actions, `expr()`
  conditions, hooks, or serializers that consume unbounded resources.

## Hardening recommendations

- Keep the tracking server on `127.0.0.1`. For shared access, put it behind an
  authenticating reverse proxy and scope the storage directory or S3 prefix to
  that team. Disable or remove built-in example routes when they are not needed.
- Treat the persistence store like a credential store: restrict write access to
  the application identity, enable encryption at rest, and audit access.
- Use `Condition.safe_expr()` for any expression that is not written by a
  developer and checked into source control.
- Leave the pickle serializer disabled unless every writer of the store is
  trusted; prefer the JSON-based or pydantic serializers.
- Validate project names, `app_id`, and `partition_key` in your application
  before passing them to Burr when any part comes from end-user input.
- Restrict permissions on the tracking storage directory to the user running
  the application.
- Pin `apache-burr` and its extras, and upgrade to the latest minor release
  promptly when a fix is announced.
