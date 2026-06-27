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


.. _ui-notebook:

================
Notebook / Colab
================

You can launch the Burr UI directly from a Jupyter notebook or Google Colab using the
``%burr_ui`` IPython magic, without needing a separate terminal.

------------------
Jupyter Notebook
------------------

.. code-block:: python

    # Load the extension and print the URL
    %load_ext burr.integrations.notebook
    %burr_ui
    # → "Burr UI: http://127.0.0.1:7241"

The magic starts the tracking server on port ``7241`` if it isn't already running and
prints the URL to access it.

--------------
Google Colab
--------------

In Colab, the kernel runs remotely, so you need to forward the port to your browser:

.. code-block:: python

    %load_ext burr.integrations.notebook
    %burr_ui

.. code-block:: python

    from google.colab import output
    output.serve_kernel_port_as_window(7241)   # opens a new browser window
    output.serve_kernel_port_as_iframe(7241)   # or inline as an iframe
