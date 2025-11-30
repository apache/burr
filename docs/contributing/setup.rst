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


=====
Setup
=====

These instructions will be assuming use of `pip <https://pip.pypa.io/en/stable/>`_ and `virtualenv <https://virtualenv.pypa.io/>`_.
Replace with your package manager of choice if you prefer.

----------
Clone/fork
----------

To get started, create a fork of Burr on the github UI, and clone it to your local machine.

.. code-block:: bash

    git clone https://github.com/<your_space>/burr.git


----------
Installing
----------

Next you'll want to ``cd`` into the directory and install
``burr`` in developer mode:

.. code-block:: bash

    cd burr
    pip install -e ".[developer]"

You can also use dependency group:

.. code-block:: bash

    pip install -e . --group dev

or, if you use ``uv``:

.. code-block:: bash

    uv sync

The latter command will automatically create and install virtual env if one does not exist and will
automatically install the project in editable mode with all developer dependencies defined in dev
dependency group.

This will install all potential dependencies. Burr will work with ``python >=3.9``.

------------------
Linting/Pre-Commit
------------------

Burr has pre-commit hooks enabled. This comes with the ``developer`` extras.
You can always run the pre-commit hooks manually (on all files). Do this
if it somehow wasn't configured and its in a bad state.

.. code-block:: bash

    pre-commit run --all

For the UI, we leverage husky and lint-staged to run the pre-commit hooks on the client side.
This actually runs pre-commits for the whole repository, so you can run through husky if you want.

You can also run the pre-commit hooks for the UI manually:

.. code-block:: bash

    npm run lint:fix
    npm run format:fix

from within the ``telemetry/ui`` directory.
