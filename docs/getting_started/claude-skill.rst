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


==================
Claude Code Skill
==================

Apache Burr includes a comprehensive Claude Code skill that makes Claude an expert in helping you build Burr applications.

What is the Claude Code Skill?
===============================

The Burr Claude skill is a plugin for `Claude Code <https://claude.com/claude-code>`_, Anthropic's official CLI tool. When active, it teaches Claude how to:

* Build new Burr applications from scratch
* Write properly structured actions and transitions
* Follow best practices and design patterns
* Debug common issues
* Provide working code examples
* Review your code for correctness

Installation
============

Option 1: Install from GitHub (Easiest)
----------------------------------------

Use the Claude CLI to install directly from GitHub:

.. code-block:: bash

    # Install to personal skills directory
    claude skill install https://github.com/apache/burr/.claude/skills/burr

    # Or install to your current project
    claude skill install https://github.com/apache/burr/.claude/skills/burr --project

Option 2: Manual Personal Installation
---------------------------------------

Copy the skill to your personal Claude skills directory:

.. code-block:: bash

    # Clone the Burr repository
    git clone https://github.com/apache/burr

    # Copy skill to personal directory
    cp -r burr/.claude/skills/burr ~/.claude/skills/

Option 3: Manual Project Installation
--------------------------------------

For team projects, copy the skill to your project's ``.claude/skills/`` directory:

.. code-block:: bash

    # From your project root
    cp -r /path/to/burr/.claude/skills/burr .claude/skills/

Verify Installation
-------------------

Check that the skill is available:

.. code-block:: bash

    # In Claude Code, try:
    /burr --help

Or ask Claude naturally:

    "Help me build a Burr application"

Usage
=====

Manual Invocation
-----------------

Use the ``/burr`` command to explicitly invoke the skill:

.. code-block:: text

    /burr How do I create a streaming action?

    /burr Review this action for best practices

    /burr Show me an example of parallel execution

Automatic Invocation
--------------------

Claude automatically loads the skill when it detects you're working with Burr:

.. code-block:: text

    "I'm building a chatbot with Burr"

    "Why isn't my action updating the state?"

    "Show me how to add persistence"

What Can It Do?
===============

Code Generation
---------------

Ask Claude to generate complete Burr applications:

**Example:**

.. code-block:: text

    "Create a Burr application for a RAG chatbot with document retrieval and reranking"

Claude will generate:

* Action functions with proper ``@action`` decorators
* State machine transitions with conditions
* Tracking configuration
* Complete application setup

Code Review
-----------

Get feedback on your Burr code:

**Example:**

.. code-block:: text

    "Review this application for best practices"

Claude will check:

* Correct ``reads`` and ``writes`` declarations
* State immutability
* Transition coverage
* Error handling
* Performance considerations

Learning & Examples
-------------------

Get working examples for common patterns:

**Example:**

.. code-block:: text

    "Show me how to implement retry logic"

Claude provides:

* Complete working code
* Explanation of the pattern
* Best practices
* References to documentation

Debugging Help
--------------

Troubleshoot issues with Claude's help:

**Example:**

.. code-block:: text

    "My state machine is looping infinitely"

Claude will:

* Analyze transition logic
* Suggest using ``.visualize()``
* Provide solutions
* Reference troubleshooting docs

Skill Contents
==============

The skill includes comprehensive documentation:

API Reference
-------------

Complete documentation of Burr's API:

* Actions and decorators
* State management
* ApplicationBuilder
* Transitions and conditions
* Persistence
* Tracking and hooks

Examples
--------

Working code examples for:

* Basic chatbots
* Streaming actions
* Parallel execution
* Error handling and retries
* RAG patterns
* State persistence
* Testing

Design Patterns
---------------

Best practices and architectural guidance:

* Single responsibility actions
* State immutability
* Deterministic actions
* Error recovery patterns
* Multi-stage pipelines
* Branching decision trees

Troubleshooting
---------------

Solutions for common issues:

* Installation problems
* State machine loops
* State not updating
* Persistence issues
* Performance optimization

Common Use Cases
================

Building a Chatbot
------------------

.. code-block:: text

    "Help me build a multi-modal chatbot with Burr"

Claude will create a complete chatbot with:

* User input action
* LLM response action
* State management for chat history
* Transitions for conversation flow

Adding Features
---------------

.. code-block:: text

    "Add streaming responses to my chatbot"

Claude will:

* Show how to convert to a streaming action
* Provide the generator pattern
* Update the application setup

Debugging
---------

.. code-block:: text

    "My action isn't updating state, what's wrong?"

Claude will:

* Review your code
* Identify the issue (likely missing ``return``)
* Provide the fix
* Explain why it matters

Tips for Best Results
======================

1. **Be specific** - "Help me add retry logic to my fetch action" is better than "help with errors"

2. **Show your code** - Claude works best when it can see what you're building

3. **Ask for examples** - "Show me an example of..." gets working code

4. **Reference the skill's docs** - Ask Claude to check the API reference or patterns guide

5. **Use visualization** - Ask Claude to suggest using ``app.visualize()`` when debugging

Example Conversation
====================

Here's a typical interaction:

.. code-block:: text

    You: I want to build a Burr application that processes documents through multiple stages

    Claude: I'll help you create a multi-stage document processing pipeline with Burr.
    Let me create actions for each stage...

    [Claude generates code with actions for validation, transformation, enrichment, and output]

    You: How do I add error handling?

    Claude: I'll show you how to add error recovery with retries. Here's the pattern...

    [Claude adds error handling actions and transitions]

    You: Can you review this code?

    Claude: Let me check your application for best practices...

    [Claude reviews and provides feedback]

Integration with Development
=============================

The skill integrates seamlessly with your development workflow:

* **During design** - Get help planning your state machine architecture
* **While coding** - Generate boilerplate and follow patterns
* **When debugging** - Troubleshoot issues and understand errors
* **In code review** - Verify best practices are followed

Customizing the Skill
======================

You can customize the skill for your needs:

1. Edit ``SKILL.md`` to change instructions
2. Add your own examples to ``examples.md``
3. Update ``patterns.md`` with team-specific practices
4. Extend ``api-reference.md`` with custom actions

Example customization:

.. code-block:: bash

    cd ~/.claude/skills/burr
    # Edit the skill files
    vim examples.md

Updating the Skill
==================

To get the latest version:

.. code-block:: bash

    cd /path/to/burr
    git pull
    cp -r .claude/skills/burr ~/.claude/skills/

Related Resources
=================

* `Claude Code Documentation <https://docs.claude.com/claude-code>`_
* `Burr Examples <https://github.com/apache/burr/tree/main/examples>`_
* `Burr Discord <https://discord.gg/6Zy2DwP4f3>`_

FAQ
===

**Do I need Burr installed to use the skill?**

No, but Claude can help you install it when needed.

**Can I use this with other frameworks?**

Yes! Burr integrates well with LangChain, LlamaIndex, Apache Hamilton, and others.

**Will this work with older Burr versions?**

The skill is designed for current Burr versions. Some APIs may differ in older releases.

**How do I disable the skill?**

Rename the skill directory:

.. code-block:: bash

    mv ~/.claude/skills/burr ~/.claude/skills/burr.disabled

**Can I share my customizations?**

Yes! Contribute improvements back to the project via pull request.

Contributing
============

Found an issue or want to improve the skill? We welcome contributions!

Reporting Issues
----------------

If you find a bug or have a suggestion:

1. Check existing issues at https://github.com/apache/burr/issues
2. Open a new issue with:

   * Clear description of the problem or suggestion
   * Steps to reproduce (for bugs)
   * Expected vs actual behavior
   * Burr version and environment details

Contributing Improvements
-------------------------

We especially appreciate pull requests! To contribute:

1. Fork the repository
2. Edit the skill files in ``.claude/skills/burr/``
3. Test your changes with Claude Code
4. Submit a PR to https://github.com/apache/burr with:

   * Clear description of what you changed and why
   * Examples showing the improvement
   * Any relevant issue references

Small fixes like typos, improved examples, or clearer explanations are always welcome!

The Burr community appreciates all contributions, big and small.
