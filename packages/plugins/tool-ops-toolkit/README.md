# Ops Toolkit Tool Plugin

`tool-ops-toolkit` is a sample but useful community tool plugin for the Agent Adapter Runtime.

It adds two read-only agent tools:

- `tool_ops__capability_snapshot`
  Returns a concise summary of active and blocked capabilities, including pricing.
- `tool_ops__job_digest`
  Returns a compact digest of recent jobs, status counts, and tracked payment volume.

This package is meant to be copied and adapted by plugin authors. It shows:

- how to implement `ToolPlugin`
- how to expose multiple `ToolDefinition`s
- how to use `RuntimeAPI` safely
- how to package a plugin through the `agent_adapter.tools` entry-point group

Example config:

```yaml
tools:
  - id: ops-toolkit
```

Or load it directly from a file during local development:

```yaml
tools:
  - module: /absolute/path/to/tool_ops_toolkit/plugin.py
    class_name: OpsToolkitPlugin
    config:
      default_job_limit: 12
```
