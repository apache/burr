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

# burr has moved to apache-burr

This package is a redirect. Burr is now developed under the Apache
Software Foundation as **Apache Burr (incubating)**.

## Migration

Replace `burr` with `apache-burr` in your dependencies:

```bash
pip install apache-burr
```

Extras carry over identically (`apache-burr[start]`, `apache-burr[tracking-server]`,
etc.). The Python import path is unchanged — `from burr.core import ...`
keeps working — because installing `apache-burr` installs the same `burr`
Python module.

For documentation and getting started, see:
- https://burr.apache.org/
- https://github.com/apache/burr

This `burr` package on PyPI exists to keep `pip install burr` working for
users on muscle memory or pinned dependencies. It contains no source code;
it simply pins `apache-burr` of the matching version.
