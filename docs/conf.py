# Licensed to the Apache Software Foundation (ASF) under one
# or more contributor license agreements.  See the NOTICE file
# distributed with this work for additional information
# regarding copyright ownership.  The ASF licenses this file
# to you under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance
# with the License.  You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
# KIND, either express or implied.  See the License for the
# specific language governing permissions and limitations
# under the License.

# Configuration file for the Sphinx documentation builder.
#
# For the full list of built-in configuration values, see the documentation:
# https://www.sphinx-doc.org/en/master/usage/configuration.html

# -- Project information -----------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#project-information
import subprocess

apache_footer = """
<div class="apache-footer">
    <img width="200" src="/_static/apache-incubator-logo.svg" alt="Apache Incubator Logo" class="apache-incubator-logo">
    <div class="apache-notice">
        <p>Apache Burr is an effort undergoing incubation at The Apache Software Foundation (ASF), sponsored by the Apache Incubator. Incubation is required of all newly accepted projects until a further review indicates that the infrastructure, communications, and decision making process have stabilized in a manner consistent with other successful ASF projects. While incubation status is not necessarily a reflection of the completeness or stability of the code, it does indicate that the project has yet to be fully endorsed by the ASF.</p>
    </div>
    <div class="apache-copyright">
        <p>Apache, the names of Apache projects, and the feather logo are either registered trademarks or trademarks of the Apache Software Foundation in the United States and/or other countries.</p>
    </div>
</div>
"""

project = "Apache Burr"
copyright = "The Apache Software Foundation, Licensed under the Apache License, Version 2.0."
author = "Apache Burr PMC"

# -- General configuration ---------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#general-configuration

extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.autosummary",
    "myst_nb",
    "sphinx_sitemap",
    "sphinx_toolbox.collapse",
]

templates_path = ["_templates"]
exclude_patterns = ["_build", "Thumbs.db", ".DS_Store"]

html_theme = "furo"
html_static_path = ["_static"]
html_favicon = "_static/favicon.ico"

html_css_files = [
    "custom.css",
    "testimonials.css",
]

html_title = "Apache Burr"
html_theme_options = {
    "source_repository": "https://github.com/apache/burr",
    "source_branch": "main",
    "source_directory": "docs/",
    "light_css_variables": {
        "color-announcement-background": "#ffba00",
        "color-announcement-text": "#091E42",
    },
    "dark_css_variables": {
        "color-announcement-background": "#ffba00",
        "color-announcement-text": "#091E42",
    },
    "footer_icons": [
        {
            "name": "Apache Stuff",
            "html": apache_footer,
            "url": "https://incubator.apache.org/",
        },
    ],
}

nb_execution_mode = "off"

exclude_patterns = ["README-internal.md"]

autodoc_typehints_format = "short"
python_maximum_signature_line_length = 100
python_use_unqualified_type_names = True

# -- for sitemap extension
GIT_BRANCH_OUTPUT = subprocess.check_output(["git", "rev-parse", "--abbrev-ref", "HEAD"])
current_branch = GIT_BRANCH_OUTPUT.decode().strip()
if current_branch == "main":
    html_baseurl = "https://burr.apache.org/"
else:
    html_baseurl = "https://burr.staged.apache.org/"
html_extra_path = ["robots.txt"]
sitemap_locales = [None]
sitemap_url_scheme = "{link}"
