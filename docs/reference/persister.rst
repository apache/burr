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
State Persistence
=================

.. _persistersref:

Burr provides a set of tools to make loading and saving state easy. These are functions
that will be used by lifecycle hooks to save and load state.

We currently support the following database integrations:

.. table:: Burr Implemented Persisters
    :widths: auto

    +-------------+-----------------------------------------------------------------+---------------------------------------------------------------------+
    | Database    | Sync                                                            | Async                                                               |
    +=============+===========+=====================================================+===============+=====================================================+
    | SQLite      | sqlite3   | :ref:`SQLitePersister <syncsqliteref>`              | aiosqlite     | :ref:`AsyncSQLitePersister <asyncsqliteref>`        |
    +-------------+-----------+-----------------------------------------------------+---------------+-----------------------------------------------------+
    | PostgreSQL  | psycopg2  | :ref:`PostgreSQLPersister <syncpostgresref>`        | asyncpg       | :ref:`AsyncPostgreSQLPersister <asyncpostgresref>`  |
    +-------------+-----------+-----------------------------------------------------+---------------+-----------------------------------------------------+
    | Redis       | redis     | :ref:`RedisBasePersister <syncredisref>`            | redis.asyncio | :ref:`AsyncRedisBasePersister <asyncredisref>`      |
    +-------------+-----------+-----------------------------------------------------+---------------+-----------------------------------------------------+
    | MongoDB     | pymongo   | :ref:`MongoDBBasePersister <syncmongoref>`          | ❌            | ❌                                                  |
    +-------------+-----------+-----------------------------------------------------+---------------+-----------------------------------------------------+
    | Aerospike   | aerospike | :ref:`AerospikePersister <syncaerospikeref>`        | ❌            | ❌                                                  |
    +-------------+-----------+-----------------------------------------------------+---------------+-----------------------------------------------------+

We follow the naming convention ``b_dependency-library``, where the ``b_`` is used to avoid name
clashing with the underlying library. We chose the library name in case we implement the same database
persister with different dependency libraries to keep the class naming convention.

If you want to implement your own state persister (to bridge it with a database), you should implement
the ``BaseStatePersister`` or the ``AsyncBaseStatePersister`` interface.

.. autoclass:: burr.core.persistence.BaseStatePersister
   :members:
   :show-inheritance:
   :inherited-members:

   .. automethod:: __init__

Internally, this interface combines the following two interfaces:

.. autoclass:: burr.core.persistence.BaseStateLoader
   :members:

   .. automethod:: __init__

.. autoclass:: burr.core.persistence.BaseStateSaver
    :members:
    :show-inheritance:
    :inherited-members:

    .. automethod:: __init__

Note we also have the corresponding async implementations:

.. autoclass:: burr.core.persistence.AsyncBaseStatePersister
   :members:
   :show-inheritance:
   :inherited-members:

   .. automethod:: __init__

Internally, this interface combines the following two interfaces:

.. autoclass:: burr.core.persistence.AsyncBaseStateLoader
   :members:

   .. automethod:: __init__

.. autoclass:: burr.core.persistence.AsyncBaseStateSaver
    :members:
    :show-inheritance:
    :inherited-members:

    .. automethod:: __init__



Supported Sync Implementations
================================

Currently we support the following, although we highly recommend you contribute your own! We will be adding more shortly.

.. _syncsqliteref:

.. autoclass:: burr.core.persistence.SQLitePersister
   :members:

   .. automethod:: __init__

.. _syncpostgresref:

.. autoclass:: burr.integrations.persisters.b_psycopg2.PostgreSQLPersister
   :members:

   .. automethod:: __init__

.. _syncredisref:

.. autoclass:: burr.integrations.persisters.b_redis.RedisBasePersister
   :members:

   .. automethod:: __init__

.. _syncmongoref:

.. autoclass:: burr.integrations.persisters.b_pymongo.MongoDBBasePersister
   :members:

   .. automethod:: __init__

.. _syncaerospikeref:

.. autoclass:: burr.integrations.persisters.b_aerospike.AerospikePersister
   :members:

   .. automethod:: __init__



Note that the :py:class:`LocalTrackingClient <burr.tracking.client.LocalTrackingClient>` leverages the :py:class:`BaseStateLoader <burr.core.persistence.BaseStateLoader>` to allow loading state,
although it uses different mechanisms to save state (as it tracks more than just state).


Supported Async Implementations
================================

.. _asyncpersistersref:

Currently we support the following, although we highly recommend you contribute your own! We will be adding more shortly.

.. _asyncsqliteref:

.. autoclass:: burr.integrations.persisters.b_aiosqlite.AsyncSQLitePersister
   :members:

   .. automethod:: __init__

.. _asyncpostgresref:

.. autoclass:: burr.integrations.persisters.b_asyncpg.AsyncPostgreSQLPersister
   :members:

   .. automethod:: __init__

.. _asyncredisref:

.. autoclass:: burr.integrations.persisters.b_redis.AsyncRedisBasePersister
   :members:

   .. automethod:: __init__
