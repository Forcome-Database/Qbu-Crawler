function getCfg(api) {
  return api?.pluginConfig ?? {};
}

function nowId(prefix) {
  return prefix + "-" + Date.now() + "-" + Math.random().toString(16).slice(2);
}

async function parseJsonOrSseResponse(resp, expectedId, opts) {
  var signal = opts?.signal;
  var timeoutMs = opts?.timeoutMs;
  var ct = resp.headers.get("content-type") || "";

  if (ct.includes("application/json")) {
    return await resp.json();
  }

  if (ct.includes("text/event-stream")) {
    var reader = resp.body?.getReader?.();
    if (!reader) throw new Error("SSE response had no readable body");

    var decoder = new TextDecoder("utf-8");
    var buf = "";
    var deadline = Number.isFinite(timeoutMs) ? Date.now() + timeoutMs : null;

    while (true) {
      if (signal?.aborted) throw new Error("Aborted");
      if (deadline && Date.now() > deadline) throw new Error("Timed out waiting for SSE response");

      var chunk = await reader.read();
      if (chunk.done) {
        // Process any remaining data in buffer before breaking
        buf += decoder.decode(new Uint8Array(0), { stream: false });
        if (buf.trim()) buf += "\n\n";
        // Fall through to process remaining buffer, then break after
      } else {
        buf += decoder.decode(chunk.value, { stream: true });
      }

      var idx;
      while ((idx = buf.indexOf("\n\n")) !== -1) {
        var rawEvent = buf.slice(0, idx);
        buf = buf.slice(idx + 2);

        var dataLines = rawEvent
          .split("\n")
          .map(function (l) { return l.replace(/\r$/, ""); })
          .filter(function (l) { return l.startsWith("data:"); })
          .map(function (l) { return l.slice(5).trimStart(); });

        if (dataLines.length === 0) continue;

        var dataStr = dataLines.join("\n");
        if (!dataStr) continue;

        var json;
        try {
          json = JSON.parse(dataStr);
        } catch (e) {
          continue;
        }

        var candidates = Array.isArray(json) ? json : [json];
        for (var i = 0; i < candidates.length; i++) {
          var msg = candidates[i];
          if (msg && typeof msg === "object" && "id" in msg && msg.id === expectedId) {
            reader.cancel();
            return msg;
          }
        }

        if (!expectedId) {
          reader.cancel();
          return json;
        }
      }

      if (chunk.done) break;
    }

    throw new Error("SSE stream ended before JSON-RPC response was received");
  }

  if (resp.status === 202) return null;

  var text = await resp.text().catch(function () { return ""; });
  throw new Error("Unexpected content-type: " + (ct || "(none)") + "; status=" + resp.status);
}

function normalizeMcpToolResult(mcpResult) {
  if (mcpResult && typeof mcpResult === "object" && Array.isArray(mcpResult.content)) {
    return {
      content: mcpResult.content,
      details: mcpResult,
    };
  }

  return {
    content: [{ type: "text", text: typeof mcpResult === "string" ? mcpResult : JSON.stringify(mcpResult, null, 2) }],
    details: mcpResult ?? null,
  };
}

function createMcpClient(options) {
  var endpoint = options.endpoint;
  var protocolVersion = options.protocolVersion;
  var timeoutMs = options.timeoutMs;
  var api = options.api;
  var log = options.log;

  var mcpSessionId = null;
  var initialized = false;

  async function postJsonRpc(message, callOpts) {
    var signal = callOpts?.signal;
    var headers = {
      "Content-Type": "application/json",
      "Accept": "application/json, text/event-stream",
    };
    if (mcpSessionId) headers["Mcp-Session-Id"] = mcpSessionId;

    var resp = await fetch(endpoint, {
      method: "POST",
      headers: headers,
      body: JSON.stringify(message),
      signal: signal,
    });

    if (resp.status === 404 && mcpSessionId) {
      mcpSessionId = null;
      initialized = false;
      return postJsonRpc(message, callOpts);
    }

    var sid = resp.headers.get("mcp-session-id") || resp.headers.get("Mcp-Session-Id");
    if (sid && !mcpSessionId) mcpSessionId = sid;

    return resp;
  }

  async function ensureInitialized(callOpts) {
    if (initialized) return;

    var signal = callOpts?.signal;
    var initId = nowId("init");
    var initReq = {
      jsonrpc: "2.0",
      id: initId,
      method: "initialize",
      params: {
        protocolVersion: protocolVersion,
        capabilities: {
          roots: { listChanged: false },
          sampling: {},
        },
        clientInfo: {
          name: "OpenClaw",
          version: api?.config?.meta?.lastTouchedVersion ?? "unknown",
        },
      },
    };

    var resp = await postJsonRpc(initReq, { signal: signal });
    var json = await parseJsonOrSseResponse(resp, initId, { signal: signal, timeoutMs: timeoutMs });

    if (json?.error) {
      throw new Error("MCP initialize failed: " + (json.error.message || JSON.stringify(json.error)));
    }

    var notif = { jsonrpc: "2.0", method: "notifications/initialized" };
    await postJsonRpc(notif, { signal: signal });

    initialized = true;
  }

  async function callTool(name, args, callOpts) {
    var signal = callOpts?.signal;
    await ensureInitialized({ signal: signal });

    var id = nowId("tool-" + name);
    var req = {
      jsonrpc: "2.0",
      id: id,
      method: "tools/call",
      params: {
        name: name,
        arguments: args ?? {},
      },
    };

    var resp = await postJsonRpc(req, { signal: signal });
    var json = await parseJsonOrSseResponse(resp, id, { signal: signal, timeoutMs: timeoutMs });

    var msg = Array.isArray(json) ? json.find(function (m) { return m?.id === id; }) : json;

    if (msg?.error) {
      throw new Error("MCP tool error (" + name + "): " + (msg.error?.message || JSON.stringify(msg.error)));
    }

    return msg?.result;
  }

  return { callTool: callTool };
}

var TOOLS = [
  {
    name: "start_scrape",
    description: "Submit product URLs for scraping. Params: urls (array of URL strings).",
    parameters: {
      type: "object",
      properties: {
        urls: { type: "array", items: { type: "string" }, description: "Product page URLs to scrape" }
      },
      required: ["urls"]
    }
  },
  {
    name: "start_collect",
    description: "Collect products from a category page then scrape each. Params: category_url (string), max_pages (int, 0=all).",
    parameters: {
      type: "object",
      properties: {
        category_url: { type: "string", description: "Category page URL" },
        max_pages: { type: "integer", description: "Max pages to collect, 0 for all" }
      },
      required: ["category_url"]
    }
  },
  {
    name: "get_task_status",
    description: "Query task real-time status and progress. Params: task_id (string).",
    parameters: {
      type: "object",
      properties: {
        task_id: { type: "string", description: "Task ID returned by start_scrape or start_collect" }
      },
      required: ["task_id"]
    }
  },
  {
    name: "list_tasks",
    description: "List crawler task records. Params: status (optional: pending/running/completed/failed/cancelled), limit (int, default 20).",
    parameters: {
      type: "object",
      properties: {
        status: { type: "string", description: "Filter by status: pending, running, completed, failed, cancelled. Empty for all." },
        limit: { type: "integer", description: "Max number of tasks to return" }
      }
    }
  },
  {
    name: "cancel_task",
    description: "Cancel a running or pending task. Params: task_id (string).",
    parameters: {
      type: "object",
      properties: {
        task_id: { type: "string", description: "Task ID to cancel" }
      },
      required: ["task_id"]
    }
  },
  {
    name: "list_products",
    description: "Search and filter scraped products. All params optional: site (basspro/meatyourmaker), search (keyword), min_price, max_price, stock_status, sort_by, order, limit, offset.",
    parameters: {
      type: "object",
      properties: {
        site: { type: "string", description: "Site filter: basspro or meatyourmaker" },
        search: { type: "string", description: "Product name keyword search" },
        min_price: { type: "number", description: "Min price filter (USD), -1 to skip" },
        max_price: { type: "number", description: "Max price filter (USD), -1 to skip" },
        stock_status: { type: "string", description: "Stock status: in_stock, out_of_stock, unknown" },
        sort_by: { type: "string", description: "Sort field: price, rating, review_count, scraped_at, name" },
        order: { type: "string", description: "Sort direction: asc or desc" },
        limit: { type: "integer", description: "Page size, default 20" },
        offset: { type: "integer", description: "Pagination offset, default 0" }
      }
    }
  },
  {
    name: "get_product_detail",
    description: "Get full product info with recent reviews and price snapshots. Provide one of: product_id, url, or sku.",
    parameters: {
      type: "object",
      properties: {
        product_id: { type: "integer", description: "Product ID, -1 to skip" },
        url: { type: "string", description: "Product page URL" },
        sku: { type: "string", description: "Product SKU" }
      }
    }
  },
  {
    name: "query_reviews",
    description: "Query product reviews with filters. All params optional: product_id, site, min_rating, max_rating, author, keyword, has_images, sort_by, order, limit, offset.",
    parameters: {
      type: "object",
      properties: {
        product_id: { type: "integer", description: "Filter by product ID, -1 to skip" },
        site: { type: "string", description: "Site filter: basspro or meatyourmaker" },
        min_rating: { type: "number", description: "Min rating (0-5), -1 to skip" },
        max_rating: { type: "number", description: "Max rating (0-5), -1 to skip" },
        author: { type: "string", description: "Author name search" },
        keyword: { type: "string", description: "Search in title and body" },
        has_images: { type: "string", description: "Filter by images: true, false, or empty for all" },
        sort_by: { type: "string", description: "Sort: rating, scraped_at, date_published" },
        order: { type: "string", description: "Sort direction: asc or desc" },
        limit: { type: "integer", description: "Page size, default 20" },
        offset: { type: "integer", description: "Pagination offset, default 0" }
      }
    }
  },
  {
    name: "get_price_history",
    description: "Get product price and stock change history. Params: product_id (required), days (default 30).",
    parameters: {
      type: "object",
      properties: {
        product_id: { type: "integer", description: "Product ID" },
        days: { type: "integer", description: "Number of days of history, default 30" }
      },
      required: ["product_id"]
    }
  },
  {
    name: "get_stats",
    description: "Get database statistics: product counts by site, review totals, avg price, avg rating, last scrape time.",
    parameters: {
      type: "object",
      properties: {}
    }
  },
  {
    name: "execute_sql",
    description: "Execute read-only SQL on the crawler database. Only SELECT allowed, max 500 rows, 5s timeout. Tables: products, product_snapshots, reviews, tasks.",
    parameters: {
      type: "object",
      properties: {
        sql: { type: "string", description: "SELECT SQL query" }
      },
      required: ["sql"]
    }
  }
];

export default {
  id: "mcp-products",
  name: "MCP Products (Streamable HTTP)",
  description: "Expose a remote MCP server as OpenClaw tools",
  configSchema: {
    type: "object",
    properties: {
      endpoint: { type: "string" },
      protocolVersion: { type: "string" },
      timeoutMs: { type: "integer" },
    },
    additionalProperties: false,
  },

  register(api) {
    var cfg = getCfg(api);
    var endpoint = cfg.endpoint || "http://8.153.109.16:15087/mcp/";
    var protocolVersion = cfg.protocolVersion || "2025-03-26";
    var timeoutMs = Number.isFinite(cfg.timeoutMs) ? cfg.timeoutMs : 60000;
    var log = api.logger ?? console;

    var client = createMcpClient({
      endpoint: endpoint,
      protocolVersion: protocolVersion,
      timeoutMs: timeoutMs,
      api: api,
      log: log,
    });

    for (var i = 0; i < TOOLS.length; i++) {
      var tool = TOOLS[i];
      (function (t) {
        api.registerTool({
          name: t.name,
          label: t.name,
          description: t.description,
          parameters: t.parameters,
          execute: async function (_toolCallId, params, signal) {
            var result = await client.callTool(t.name, params ?? {}, { signal: signal });
            return normalizeMcpToolResult(result);
          },
        });
      })(tool);
    }

    log.info?.("[mcp-products] registered " + TOOLS.length + " MCP tools against " + endpoint);
  },
};
