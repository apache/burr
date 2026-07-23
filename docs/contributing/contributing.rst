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


.. _contributing:

============
Contributing
============

Please read the `code of conduct <https://github.com/apache/burr?tab=coc-ov-file#readme>`_
prior to contributing. Then follow these guidelines:

#. Create a fork of the repository.
#. Ensure all tests pass.
#. Make a PR to the main repository.
#. Ping one of the maintainers to review your PR.

-----------------------
Contribution guidelines
-----------------------

Please:

#. Keep your commits modular
#. Add descriptive commit messages
#. Attach a PR to an issue if applicable
#. Ensure all new features have tests
#. Add documentation for new features

Examples
--------

All examples must have the following files:
1. A ``README.md`` file that describes the example -- this should follow the pattern of the others
2. A ``requirements.txt`` file that lists the dependencies for the example
3. An ``application.py`` file whose mainline runs a simple version of the example + generates the DAG to
4. A ``statemachine.png`` file that shows the DAG for the example
3. A `notebook.ipynb` file that uses the example in a

The ``notebook.ipynb`` can import stuff from the ``application.py``, or redefine it as an example. If you have something
that does not fit this, or is a prototype but you want to push it in, you can fit in under the ``half-baked`` directory.

---------------
Developer notes
---------------

CLI
---

Burr comes with a `cli` that is both user/developer facing.

**this is required in order to publish, do not do so otherwise**

This will be turned into a `Makefile`, but for now we have a set of commands in `pyproject.toml` that are used to
publish, etc...

To run the just the server for development:

.. code-block:: bash

    $ burr --dev-mode --no-open # will run the server on port 7241

To publish -- this will build the FE + publish the BE to the ``pypi`` prod instance. Note you have to have ``pypi`` credentials to do this:

.. code-block:: bash

    $ burr-admin-publish --prod

To generate the demo data (if you make a change to the schema, ideally forward-compatible):

.. code-block:: bash

    $ burr-admin-generate-demo-data

Not part of the CLI (yet), but running just the UI is simple:

.. code-block:: bash

        $ cd telemetry/ui
        $ npm run start

Package data
------------

Several static assets are included in the python package so we can run the UI. Namely:

1. The `examples` directory is symlinked from ``burr/examples`` to allow for package-style imports
2. The `build/` directory is symlinked from ``burr/tracking/server`` to allow for static assets referred to by the server to be included in the package. Note that this does not get committed -- this requires use of the CLI above.
