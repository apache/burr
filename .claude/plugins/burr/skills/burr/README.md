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

# Apache Burr Claude Skill

A comprehensive Claude Code skill for building stateful applications with Apache Burr.

## What is this?

This is a Claude Code skill that teaches Claude how to help you build applications using Apache Burr. When active, Claude becomes an expert in Apache Burr's APIs, best practices, and common patterns.

## Installation

### Option 1: Install from GitHub (Easiest)

```bash
# Install to personal skills directory
claude skill install https://github.com/apache/burr/.claude/skills/burr

# Or install to your current project
claude skill install https://github.com/apache/burr/.claude/skills/burr --project
```

### Option 2: Manual Install - Project-level (For teams)

Copy this skill to your project's `.claude/skills/` directory:

```bash
# From your project root
cp -r /path/to/burr/.claude/skills/burr .claude/skills/

# Or clone and copy from GitHub
git clone https://github.com/apache/burr
cp -r burr/.claude/skills/burr .claude/skills/
```

### Option 3: Manual Install - Personal scope (For individual use)

Copy to your personal Claude skills directory:

```bash
# Copy to personal skills directory
cp -r /path/to/burr/.claude/skills/burr ~/.claude/skills/

# Or clone and copy from GitHub
git clone https://github.com/apache/burr
cp -r burr/.claude/skills/burr ~/.claude/skills/
```

### Verify Installation

The skill should now appear in Claude Code's skill menu:

```bash
/burr --help
```

Or just ask Claude naturally:
```
"Help me build a Burr application for a chatbot"
```

## What Can It Do?

This skill helps you:

- **Build new Apache Burr applications** - Get help scaffolding state machines
- **Write actions** - Create properly structured action functions
- **Define transitions** - Set up conditional and default transitions
- **Add observability** - Configure tracking and the Apache Burr UI
- **Debug issues** - Troubleshoot common problems
- **Follow best practices** - Learn recommended patterns
- **Review code** - Get feedback on your Apache Burr applications

## Usage Examples

### Manual Invocation

Explicitly invoke the skill with the `/burr` command:

```
/burr How do I create a streaming action?

/burr Review this action for best practices

/burr Help me add state persistence to my app
```

### Automatic Invocation

Claude will automatically load the skill when it detects you're working with Apache Burr:

```
"I'm building a chatbot with Apache Burr and need help with the state machine"

"Why isn't my action updating the state?"

"Show me an example of parallel execution in Apache Burr"
```

## What's Included

The skill includes:

- **SKILL.md** - Main skill instructions for Claude
- **api-reference.md** - Complete API documentation
- **examples.md** - Working code examples for common patterns
- **patterns.md** - Best practices and design patterns
- **troubleshooting.md** - Solutions to common issues

Claude will reference these files to provide accurate, helpful guidance.

## Features

### Code Generation

```
"Create an Apache Burr application that processes user queries with RAG"
```

Claude will generate a complete application with actions, transitions, and tracking.

### Code Review

```
"Review my Apache Burr application for best practices"
```

Claude will check for:
- Correct `reads` and `writes` declarations
- Proper state immutability
- Complete transition coverage
- Tracking configuration
- Error handling

### Debugging Help

```
"My state machine is looping infinitely, what's wrong?"
```

Claude will:
- Analyze your transitions
- Suggest using `.visualize()` to see the graph
- Recommend fixes based on common issues with Apache Burr

### Learning & Examples

```
"Show me how to implement retries in Apache Burr"
```

Claude will provide working examples from the examples.md reference.

## Skill Configuration

### Allowed Tools

The skill permits Claude to use:
- `Read` - Read your code files
- `Grep` - Search for patterns
- `Glob` - Find files
- `Bash` - Run Python, burr CLI, and pip commands

### Automatic Activation

The skill activates when you:
- Mention "Burr" or "Apache Burr"
- Show code with `from burr.core import`
- Ask about state machines or actions
- Need help with stateful applications

## Tips for Best Results

1. **Be specific** - "Help me add retry logic to my fetch action" is better than "help with errors"

2. **Show your code** - Claude works best when it can see what you're working with

3. **Ask for examples** - "Show me an example of..." gets working code

4. **Reference the docs** - Ask Claude to check the API reference or patterns guide

5. **Use visualization** - Ask Claude to suggest using `app.visualize()` when debugging

## Examples of What to Ask

### Getting Started
- "Help me create my first Apache Burr application"
- "What's the basic structure of an Apache Burr action?"
- "Show me a simple chatbot example"

### Building Features
- "How do I add streaming to my LLM action?"
- "Show me how to implement parallel execution"
- "Help me add state persistence with SQLite"

### Debugging
- "Why isn't my transition working?"
- "My action isn't updating state, what's wrong?"
- "How do I debug an infinite loop?"

### Best Practices
- "Review this code for Apache Burr best practices"
- "Is this the right way to structure my state machine?"
- "How should I handle errors in actions?"

## Updating the Skill

To get the latest version:

```bash
cd /path/to/burr
git pull
cp -r .claude/skills/burr ~/.claude/skills/
```

## Integration with Apache Burr Project

If you're working in the Apache Burr repository itself, the skill is already available at `.claude/skills/burr/`.

## Contributing

Found an issue or want to improve the skill? We welcome contributions!

### Reporting Issues

If you find a bug or have a suggestion:

1. Check existing issues: https://github.com/apache/burr/issues
2. Open a new issue with:
   - Clear description of the problem or suggestion
   - Steps to reproduce (for bugs)
   - Expected vs actual behavior
   - Burr version and environment details

### Contributing Improvements

We especially appreciate pull requests! To contribute:

1. Fork the repository
2. Edit the skill files in `.claude/skills/burr/`
3. Test your changes with Claude Code
4. Submit a PR to https://github.com/apache/burr with:
   - Clear description of what you changed and why
   - Examples showing the improvement
   - Any relevant issue references

Small fixes like typos, improved examples, or clearer explanations are always welcome!

## Related Resources

- **Apache Burr Documentation**: https://burr.apache.org/
- **GitHub**: https://github.com/apache/burr
- **Examples**: See `examples/` directory in the Apache Burr repository
- **Discord**: https://discord.gg/6Zy2DwP4f3

## FAQ

**Q: Do I need Apache Burr installed to use this skill?**

A: No, but Claude can help you install it: `pip install "burr[start]"`

**Q: Can I customize the skill?**

A: Yes! Edit the files in `.claude/skills/burr/` to customize behavior, add your own examples, or modify the API reference.

**Q: Will this work with older versions of Apache Burr?**

A: This skill is designed for current Apache Burr versions. Some APIs may differ in older versions.

**Q: Can I use this skill with other frameworks?**

A: Yes! Apache Burr integrates well with LangChain, LlamaIndex, Apache Hamilton, and other frameworks. The skill includes integration guidance.

**Q: How do I disable the skill temporarily?**

A: Rename the skill directory or remove it from `.claude/skills/`:
```bash
mv ~/.claude/skills/burr ~/.claude/skills/burr.disabled
```

## License

This skill is part of Apache Burr (incubating) and is licensed under the Apache License 2.0.

See the [LICENSE](../../../LICENSE) file in the root of the repository.

---

Built with ❤️ by the Apache Burr community.

For help, join our [Discord](https://discord.gg/6Zy2DwP4f3) or open an issue on [GitHub](https://github.com/apache/burr/issues).
