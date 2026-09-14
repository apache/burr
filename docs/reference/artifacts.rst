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


=================
Artifact Storage
=================

.. _artifactsref:

Burr provides a set of tools for storing large values (files, images, dataframes, ...) outside
of :py:class:`State <burr.core.state.State>`, keeping only a small reference in state. See
:doc:`../concepts/artifact-storage` for a conceptual overview and usage examples.

We currently support the following backends:

.. list-table:: Burr Implemented Artifact Stores
    :header-rows: 1
    :widths: auto

    * - Backend
      - Class
      - Extra dependency
    * - Local disk
      - :ref:`LocalFileSystemArtifactStore <localartifactstoreref>`
      - none (stdlib only)
    * - AWS S3
      - :ref:`S3ArtifactStore <s3-artifacts-integration>`
      - ``pip install "apache-burr[s3]"``

If you want to implement your own artifact store (to bridge it with a new backend), you should
implement the ``ArtifactStore`` interface.

.. autoclass:: burr.core.artifacts.ArtifactStore
   :members:
   :show-inheritance:

.. autoclass:: burr.core.artifacts.ArtifactRef
   :members:

Supported Implementations
==========================

.. _localartifactstoreref:

.. autoclass:: burr.core.artifacts.LocalFileSystemArtifactStore
   :members:

   .. automethod:: __init__

See :doc:`integrations/index` for cloud-backed implementations such as
:ref:`S3ArtifactStore <s3-artifacts-integration>`.
