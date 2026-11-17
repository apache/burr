..
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


========
Tracking
========

Reference on the Tracking/Telemetry API.
Rather, you should use this through/in conjunction with :py:meth:`burr.core.application.ApplicationBuilder.with_tracker`.

.. autoclass:: burr.tracking.LocalTrackingClient
   :members:

   .. automethod:: __init__

.. autoclass:: burr.tracking.AsyncLocalTrackingClient
   :members:

   .. automethod:: __init__

Both clients write the same on-disk format, so the Burr UI and the tracking server read either
without changes. ``ApplicationBuilder.with_tracker("local", ...)`` picks between them when the
application is built, based on whether the configured object store is asynchronous; see
:ref:`asynchronous-applications` in the tracking concept docs. Passing an instance yourself is
always honored as-is.

The OpenTelemetry wrappers mirror the split, so that ``use_otel_tracing=True`` works with either
client:

.. autoclass:: burr.integrations.opentelemetry.OpenTelemetryTracker
   :members: copy

.. autoclass:: burr.integrations.opentelemetry.AsyncOpenTelemetryTracker
   :members: copy

.. autoclass:: burr.tracking.base.AsyncTrackingClient
   :members:
