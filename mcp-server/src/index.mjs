import { spawnSync } from "node:child_process";
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { z } from "zod";

const PYTHON_BIN = process.env.BOOST_PYTHON || "python";
const BOOST_MODULE_ARGS = ["-m", "boostspace_cli.cli"];

function parseJsonEnvelope(stdout) {
  const text = String(stdout || "").trim();
  if (!text) {
    return null;
  }

  try {
    const payload = JSON.parse(text);
    if (payload && typeof payload === "object" && Object.prototype.hasOwnProperty.call(payload, "ok")) {
      return payload;
    }
  } catch {
    // fall back to line/object scans
  }

  const lines = text.split(/\r?\n/).map((line) => line.trim()).filter(Boolean);
  for (let i = lines.length - 1; i >= 0; i -= 1) {
    const line = lines[i];
    if (!line.startsWith("{")) {
      continue;
    }
    try {
      const payload = JSON.parse(line);
      if (payload && typeof payload === "object" && Object.prototype.hasOwnProperty.call(payload, "ok")) {
        return payload;
      }
    } catch {
      // Keep scanning upward for JSON line.
    }
  }

  const first = text.indexOf("{");
  const last = text.lastIndexOf("}");
  if (first >= 0 && last > first) {
    try {
      const payload = JSON.parse(text.slice(first, last + 1));
      if (payload && typeof payload === "object" && Object.prototype.hasOwnProperty.call(payload, "ok")) {
        return payload;
      }
    } catch {
      // no-op
    }
  }

  return null;
}

function runBoostJson(commandArgs) {
  const args = [...BOOST_MODULE_ARGS, ...commandArgs];
  if (!args.includes("--json")) {
    args.push("--json");
  }
  const result = spawnSync(PYTHON_BIN, args, {
    encoding: "utf-8",
    env: process.env,
    timeout: 120000,
  });

  const envelope = parseJsonEnvelope(result.stdout);
  if (!envelope) {
    const stderr = String(result.stderr || "").trim();
    const stdout = String(result.stdout || "").trim();
    throw new Error(`Command did not return JSON envelope: ${stderr || stdout || "no output"}`);
  }

  if (!envelope.ok) {
    throw new Error(String(envelope.error || "Unknown CLI error"));
  }
  return envelope;
}

function asMcpResult(data, note = null) {
  const structuredContent = data && typeof data === "object" && !Array.isArray(data)
    ? data
    : { result: data };
  return {
    content: [
      {
        type: "text",
        text: note ? `${note}\n\n${JSON.stringify(data, null, 2)}` : JSON.stringify(data, null, 2),
      },
    ],
    structuredContent,
  };
}

function registerToolCompat(server, name, metadata, handler) {
  if (typeof server.registerTool === "function") {
    server.registerTool(name, metadata, handler);
    return;
  }

  if (typeof server.tool === "function") {
    server.tool(name, metadata.description || name, metadata.inputSchema || {}, handler);
    return;
  }

  throw new Error("Unsupported MCP SDK version: no tool registration method found.");
}

function maybeAdd(args, flag, value) {
  if (value === undefined || value === null || value === "") {
    return args;
  }
  args.push(flag, String(value));
  return args;
}

function maybeBool(args, flagTrue, enabled) {
  if (enabled === true) {
    args.push(flagTrue);
  }
  return args;
}

const server = new McpServer({
  name: "boostspace-scenario-mcp",
  version: "0.1.0",
});

registerToolCompat(
  server,
  "sync_knowledge",
  {
    description: "Build local knowledge snapshot from modules, formulas, templates, and workspace assets.",
    inputSchema: {
      refreshTemplates: z.boolean().default(false),
      includePublicBlueprints: z.boolean().default(true),
      includeWorkspaceAssets: z.boolean().default(true),
      blueprintLimit: z.number().int().min(0).max(200).default(30),
    },
  },
  async ({ refreshTemplates = false, includePublicBlueprints = true, includeWorkspaceAssets = true, blueprintLimit = 30 }) => {
    const args = ["mcp", "sync"];
    if (refreshTemplates) {
      args.push("--refresh-templates");
    }
    args.push(includePublicBlueprints ? "--include-public-blueprints" : "--no-include-public-blueprints");
    args.push(includeWorkspaceAssets ? "--workspace-assets" : "--no-workspace-assets");
    args.push("--blueprint-limit", String(blueprintLimit));
    const out = runBoostJson(args);
    return asMcpResult(out.data, "Knowledge sync complete.");
  }
);

registerToolCompat(
  server,
  "knowledge_info",
  {
    description: "Read metadata from local MCP knowledge snapshot.",
    inputSchema: {},
  },
  async () => {
    const out = runBoostJson(["mcp", "info"]);
    return asMcpResult(out.data);
  }
);

registerToolCompat(
  server,
  "search_modules",
  {
    description: "Search Make/Boost module catalog from local registry.",
    inputSchema: {
      query: z.string().min(1),
      app: z.string().optional(),
      limit: z.number().int().min(1).max(200).default(20),
    },
  },
  async ({ query, app, limit = 20 }) => {
    const args = ["catalog", "search", query, "--limit", String(limit)];
    maybeAdd(args, "--app", app);
    const out = runBoostJson(args);
    return asMcpResult(out.data);
  }
);

registerToolCompat(
  server,
  "search_formulas",
  {
    description: "Search Make formula/function registry.",
    inputSchema: {
      query: z.string().min(1),
      limit: z.number().int().min(1).max(200).default(20),
    },
  },
  async ({ query, limit = 20 }) => {
    const out = runBoostJson(["formulas", "search", query, "--limit", String(limit)]);
    return asMcpResult(out.data);
  }
);

registerToolCompat(
  server,
  "search_templates_public",
  {
    description: "Search public Make templates cached in local catalog.",
    inputSchema: {
      query: z.string().optional(),
      app: z.string().optional(),
      limit: z.number().int().min(1).max(200).default(20),
      refresh: z.boolean().default(false),
    },
  },
  async ({ query, app, limit = 20, refresh = false }) => {
    const args = ["catalog", "templates", "--limit", String(limit)];
    maybeBool(args, "--refresh", refresh);
    maybeAdd(args, "--query", query);
    maybeAdd(args, "--app", app);
    const out = runBoostJson(args);
    return asMcpResult(out.data);
  }
);

registerToolCompat(
  server,
  "search_templates_workspace",
  {
    description: "Search templates available in your workspace.",
    inputSchema: {
      query: z.string().optional(),
      limit: z.number().int().min(1).max(200).default(100),
      publicOnly: z.boolean().default(false),
      teamId: z.number().int().optional(),
    },
  },
  async ({ query, limit = 100, publicOnly = false, teamId }) => {
    const args = ["scenario", "templates", "--limit", String(limit)];
    maybeAdd(args, "--query", query);
    maybeBool(args, "--public-only", publicOnly);
    maybeAdd(args, "--team-id", teamId);
    const out = runBoostJson(args);
    return asMcpResult(out.data);
  }
);

registerToolCompat(
  server,
  "get_workspace_folders",
  {
    description: "List scenario folders in workspace.",
    inputSchema: {
      query: z.string().optional(),
      limit: z.number().int().min(1).max(500).default(200),
      teamId: z.number().int().optional(),
    },
  },
  async ({ query, limit = 200, teamId }) => {
    const args = ["scenarios", "folders", "--limit", String(limit)];
    maybeAdd(args, "--query", query);
    maybeAdd(args, "--team-id", teamId);
    const out = runBoostJson(args);
    return asMcpResult(out.data);
  }
);

registerToolCompat(
  server,
  "resolve_or_create_folder",
  {
    description: "Resolve folder by name and optionally create it.",
    inputSchema: {
      name: z.string().min(1),
      createIfMissing: z.boolean().default(false),
      parentId: z.number().int().optional(),
      teamId: z.number().int().optional(),
    },
  },
  async ({ name, createIfMissing = false, parentId, teamId }) => {
    const listArgs = ["scenarios", "folders", "--query", name, "--limit", "200"];
    maybeAdd(listArgs, "--team-id", teamId);
    const listed = runBoostJson(listArgs);
    const items = Array.isArray(listed.data?.items) ? listed.data.items : [];
    const exact = items.filter((item) => String(item?.name || "").toLowerCase() === String(name).toLowerCase());
    if (exact.length > 0) {
      return asMcpResult({ resolved: true, created: false, folder: exact[0], candidates: exact });
    }

    if (!createIfMissing) {
      return asMcpResult({ resolved: false, created: false, folder: null, candidates: items });
    }

    const createArgs = ["scenarios", "folder-create", "--name", name];
    maybeAdd(createArgs, "--team-id", teamId);
    maybeAdd(createArgs, "--parent-id", parentId);
    const created = runBoostJson(createArgs);
    return asMcpResult({ resolved: true, created: true, folder: created.data, candidates: [] });
  }
);

registerToolCompat(
  server,
  "plan_scenario",
  {
    description: "Run parallel planning subagents and return structured build plan.",
    inputSchema: {
      goal: z.string().min(1),
      folderName: z.string().optional(),
      teamId: z.number().int().optional(),
      parallelism: z.number().int().min(1).max(20).default(5),
    },
  },
  async ({ goal, folderName, teamId, parallelism = 5 }) => {
    const args = ["scenario", "swarm", "--mode", "build", "--goal", goal, "--parallelism", String(parallelism)];
    maybeAdd(args, "--folder-name", folderName);
    maybeAdd(args, "--team-id", teamId);
    const out = runBoostJson(args);
    return asMcpResult(out.data);
  }
);

registerToolCompat(
  server,
  "generate_draft",
  {
    description: "Generate workflow draft using workspace templates + chosen profile.",
    inputSchema: {
      goal: z.string().min(1),
      profile: z.enum(["safe", "balanced", "fast"]).default("balanced"),
      output: z.string().optional(),
      teamId: z.number().int().optional(),
    },
  },
  async ({ goal, profile = "balanced", output, teamId }) => {
    const args = ["scenario", "draft", "--goal", goal, "--profile", profile, "--use-workspace-templates"];
    maybeAdd(args, "--output", output);
    maybeAdd(args, "--team-id", teamId);
    const out = runBoostJson(args);
    return asMcpResult(out.data);
  }
);

registerToolCompat(
  server,
  "dry_run_deploy",
  {
    description: "Run deploy preflight in dry-run mode (no scenario created).",
    inputSchema: {
      file: z.string().min(1),
      profile: z.enum(["safe", "balanced", "fast"]).default("balanced"),
      teamId: z.number().int().optional(),
      folderId: z.number().int().optional(),
      folderName: z.string().optional(),
      createFolder: z.boolean().default(false),
      allowUnknownModules: z.boolean().default(false),
      allowHttpFallback: z.boolean().default(false),
      verifyRun: z.boolean().default(false),
    },
  },
  async ({
    file,
    profile = "balanced",
    teamId,
    folderId,
    folderName,
    createFolder = false,
    allowUnknownModules = false,
    allowHttpFallback = false,
    verifyRun = false,
  }) => {
    const args = ["scenario", "deploy", "--file", file, "--dry-run", "--profile", profile];
    maybeAdd(args, "--team-id", teamId);
    maybeAdd(args, "--folder-id", folderId);
    maybeAdd(args, "--folder-name", folderName);
    maybeBool(args, "--create-folder", createFolder);
    maybeBool(args, "--allow-unknown-modules", allowUnknownModules);
    maybeBool(args, "--allow-http-fallback", allowHttpFallback);
    args.push(verifyRun ? "--verify-run" : "--no-verify-run");
    const out = runBoostJson(args);
    return asMcpResult(out.data);
  }
);

registerToolCompat(
  server,
  "debug_scenario",
  {
    description: "Run parallel debug subagents against a scenario.",
    inputSchema: {
      scenarioId: z.number().int().optional(),
      name: z.string().optional(),
      teamId: z.number().int().optional(),
      parallelism: z.number().int().min(1).max(20).default(4),
    },
  },
  async ({ scenarioId, name, teamId, parallelism = 4 }) => {
    const args = ["scenario", "swarm", "--mode", "debug", "--parallelism", String(parallelism)];
    maybeAdd(args, "--scenario-id", scenarioId);
    maybeAdd(args, "--name", name);
    maybeAdd(args, "--team-id", teamId);
    const out = runBoostJson(args);
    return asMcpResult(out.data);
  }
);

async function main() {
  const transport = new StdioServerTransport();
  await server.connect(transport);
}

main().catch((error) => {
  process.stderr.write(`MCP server failed to start: ${error?.message || String(error)}\n`);
  process.exit(1);
});
