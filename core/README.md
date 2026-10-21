# mcpywrap-core

Shared engineering and runtime implementation for mcpywrap. Install `mcpywrap`
for the complete desktop tool and the `mcpy` command. Install `mcpywrap-core`
for the minimal Python library used by embedded hosts.

Both distributions share a repository, release version and implementation.
The public library entry point is `mcpywrap_core.api.Core`. Optional groups are
`watch` and `prepare`; platform-specific capabilities are supplied by the host.

Documentation: https://github.com/EaseCation/mcpywrap/blob/main/docs/shared-core.md
