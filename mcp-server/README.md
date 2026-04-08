# Boostspace MCP Server

Local MCP server that exposes high-trust planning + dry-run deployment tools for Make/Boost.space scenarios.

## What it does

- Uses `boostspace-cli` as the execution engine.
- Exposes MCP tools for:
  - module/formula/template search
  - workspace folder lookup/create
  - parallel planning (`scenario swarm`)
  - draft generation
  - deploy dry-run preflight (safe, no creation)
  - scenario debug swarm
- Supports local knowledge snapshot sync (`boost mcp sync`) for cached context.

## Install

```bash
cd mcp-server
npm install
```

## Run

```bash
npm start
```

Environment overrides:

- `BOOST_PYTHON` (default: `python`)

The server executes:

```bash
python -m boostspace_cli.cli ... --json
```

so ensure `boostspace-cli` is installed in the selected Python environment.

## Recommended bootstrap

```bash
python -m boostspace_cli.cli mcp sync --refresh-templates --json
python -m boostspace_cli.cli mcp info --json
```

This primes local knowledge with modules, formulas, public templates, workspace assets, and blueprint candidates.
