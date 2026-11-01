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


.. _serderef:

==================================
Serialization & Deserialization
==================================

Burr provides a set of tools to make loading and saving state easy. These are functions
that will be used by lifecycle hooks to save and load state.

If you want to implement your own serialization and deserialization, you should implement
the ``serialize`` & ``deserialize`` functions, which act as an interface. ``serialize`` uses
singledispatch and operates on a Type level. While ``deserialize`` registers a string value
to a function.

.. automodule:: burr.core.serde
   :members:

Each serialize function needs to a mirror deserialize function. To know which
deserialize function to use, the serialize function needs to return a dictionary and have
``burr.core.serde.KEY`` as one of the keys mapping to the appropriate value.
This is used to identify the deserialization function to use.

``burr.core.serde.KEY`` is reserved for this. A dictionary of your own that contains it is
still saved and loaded back as is: Burr wraps it as ``burr.dict`` when serializing, so don't
use ``burr.dict`` as the key for your own deserializer.

Out of the box Implementations
==============================

The following implementations are available assuming you have the right dependencies in your environment:

LangChain Objects
^^^^^^^^^^^^^^^^^

.. automodule:: burr.integrations.serde.langchain
   :members:

Pandas Objects
^^^^^^^^^^^^^^^^^

.. automodule:: burr.integrations.serde.pandas
   :members:

Pickle-able Objects
^^^^^^^^^^^^^^^^^^^

.. automodule:: burr.integrations.serde.pickle
   :members:

Pydantic Objects
^^^^^^^^^^^^^^^^^

.. automodule:: burr.integrations.serde.pydantic
   :members:
