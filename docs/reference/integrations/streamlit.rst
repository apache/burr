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


=======================
Streamlit
=======================

Full Streamlit integration. Tough-points are utility functions.
It is likely this will adapt/change over time, so it is only recommended to use this for debugging/developing.

Install with pypi:

.. code-block:: bash

   pip install apache-burr[streamlit]

.. autoclass:: burr.integrations.streamlit.AppState
    :members:

.. autofunction:: burr.integrations.streamlit.load_state_from_log_file

.. autofunction:: burr.integrations.streamlit.get_state

.. autofunction:: burr.integrations.streamlit.update_state

.. autofunction:: burr.integrations.streamlit.render_state_machine

.. autofunction:: burr.integrations.streamlit.render_action

.. autofunction:: burr.integrations.streamlit.render_state_results

.. autofunction:: burr.integrations.streamlit.set_slider_to_current

.. autofunction:: burr.integrations.streamlit.render_explorer
