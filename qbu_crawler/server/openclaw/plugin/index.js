import TOOL_CONTRACT_ARTIFACT from "./generated/tool_contract.json" with { type: "json" };

function getCfg(api) {
  return api?.pluginConfig ?? {};
}

var TOOL_CONTRACT_INDEX = TOOL_CONTRACT_ARTIFACT?.tools ?? {};
var CONTRACT_TOOL_NAMES = Object.keys(TOOL_CONTRACT_INDEX);
var CONTRACT_TOOL_NAME_SET = new Set(CONTRACT_TOOL_NAMES);
var CONTRACT_TOOL_ORDER = [
  "get_stats",
  "list_products",
  "get_product_detail",
  "query_reviews",
  "get_price_history",
  "get_task_status",
  "list_tasks",
  "get_workflow_status",
  "list_workflow_runs",
  "list_pending_notifications",
  "get_translate_status",
  "execute_sql",
  "start_scrape",
  "start_collect",
  "cancel_task",
  "preview_scope",
  "send_filtered_report",
  "export_review_images",
  "generate_report",
  "trigger_translate",
];

function getContractTool(name) {
  var contract = TOOL_CONTRACT_INDEX?.[name];
  if (!contract || typeof contract !== "object") {
    throw new Error("Missing authoritative tool contract for " + name);
  }
  return contract;
}

function contractToolToPluginTool(name) {
  var contract = getContractTool(name);
  return {
    name: contract.name,
    description: contract.description,
    parameters: contract.input_schema,
  };
}

function missingRequiredCanonicalFields(toolName, data) {
  var required = TOOL_CONTRACT_INDEX?.[toolName]?.output_schema?.required;
  if (!Array.isArray(required) || required.length === 0 || !data || typeof data !== "object") {
    return [];
  }

  return required.filter(function (field) {
    return !(field in data) || typeof data[field] === "undefined";
  });
}

var SPEAKER_CONTEXT_BY_SESSION = new Map();
var SPEAKER_CONTEXT_MAX_AGE_MS = 6 * 60 * 60 * 1000;
var SPEAKER_CONTEXT_MAX_SIZE = 512;
var TOOL_PROVENANCE_MAX_AGE_MS = 6 * 60 * 60 * 1000;
var TOOL_PROVENANCE_MAX_SIZE = 512;

function createToolProvenanceStore() {
  return {
    activeBySession: new Map(),
    lastBySession: new Map(),
  };
}

var TOOL_PROVENANCE_STORE = createToolProvenanceStore();

function nowId(prefix) {
  return prefix + "-" + Date.now() + "-" + Math.random().toString(16).slice(2);
}

function asString(value) {
  return typeof value === "string" ? value.trim() : "";
}

function firstNonEmpty() {
  for (var i = 0; i < arguments.length; i++) {
    var value = asString(arguments[i]);
    if (value) return value;
  }
  return "";
}

function lower(value) {
  return asString(value).toLowerCase();
}

function normalizeChatType(value) {
  var text = lower(value);
  if (!text) return "";
  if (text.includes("group")) return "group";
  if (text.includes("direct") || text.includes("dm") || text.includes("private")) return "direct";
  return text;
}

function sessionKeyChatType(sessionKey) {
  var key = asString(sessionKey);
  if (!key) return "";
  if (key.includes(":group:")) return "group";
  if (key.includes(":direct:")) return "direct";
  return "";
}

function pruneSpeakerContextStore() {
  var now = Date.now();
  for (var entry of SPEAKER_CONTEXT_BY_SESSION.entries()) {
    var key = entry[0];
    var value = entry[1];
    if (!value || typeof value !== "object" || now - Number(value.capturedAt || 0) > SPEAKER_CONTEXT_MAX_AGE_MS) {
      SPEAKER_CONTEXT_BY_SESSION.delete(key);
    }
  }

  if (SPEAKER_CONTEXT_BY_SESSION.size <= SPEAKER_CONTEXT_MAX_SIZE) return;

  var ordered = Array.from(SPEAKER_CONTEXT_BY_SESSION.entries()).sort(function (a, b) {
    return Number(a[1]?.capturedAt || 0) - Number(b[1]?.capturedAt || 0);
  });

  while (ordered.length > SPEAKER_CONTEXT_MAX_SIZE) {
    var oldest = ordered.shift();
    if (oldest) SPEAKER_CONTEXT_BY_SESSION.delete(oldest[0]);
  }
}

function pushUnique(items, value) {
  var text = asString(value);
  if (!text) return;
  if (!Array.isArray(items)) return;
  if (!items.includes(text)) items.push(text);
}

function pruneToolProvenanceMap(map, fieldName) {
  var now = Date.now();
  for (var entry of map.entries()) {
    var key = entry[0];
    var value = entry[1];
    if (!value || typeof value !== "object") {
      map.delete(key);
      continue;
    }

    var ts = Number(value?.[fieldName] || value?.updatedAt || value?.createdAt || 0);
    if (!ts || now - ts > TOOL_PROVENANCE_MAX_AGE_MS) {
      map.delete(key);
    }
  }

  if (map.size <= TOOL_PROVENANCE_MAX_SIZE) return;

  var ordered = Array.from(map.entries()).sort(function (a, b) {
    var aTs = Number(a[1]?.[fieldName] || a[1]?.updatedAt || a[1]?.createdAt || 0);
    var bTs = Number(b[1]?.[fieldName] || b[1]?.updatedAt || b[1]?.createdAt || 0);
    return aTs - bTs;
  });

  while (ordered.length > TOOL_PROVENANCE_MAX_SIZE) {
    var oldest = ordered.shift();
    if (oldest) map.delete(oldest[0]);
  }
}

function pruneToolProvenanceStore(store) {
  if (!store || typeof store !== "object") return;
  pruneToolProvenanceMap(store.activeBySession, "updatedAt");
  pruneToolProvenanceMap(store.lastBySession, "archivedAt");
}

function extractSpeakerContextFromMessageEvent(event) {
  var context = event?.context ?? {};
  var metadata = context?.metadata ?? {};
  var sessionKey = firstNonEmpty(event?.sessionKey, context?.sessionKey);
  var senderId = firstNonEmpty(
    metadata?.senderId,
    context?.senderId,
    context?.userId,
    metadata?.userId,
    metadata?.targetId
  );
  var senderName = firstNonEmpty(
    metadata?.senderName,
    metadata?.senderUsername,
    context?.senderName
  );
  var conversationId = firstNonEmpty(
    context?.conversationId,
    metadata?.conversationId,
    metadata?.threadId
  );
  var channelId = firstNonEmpty(
    context?.channelId,
    metadata?.provider,
    metadata?.surface
  );
  var chatType = normalizeChatType(
    firstNonEmpty(metadata?.chatType, context?.chatType, sessionKeyChatType(sessionKey))
  );

  if (!chatType && conversationId && senderId && conversationId !== senderId) {
    chatType = "group";
  }

  if (!sessionKey) return null;

  return {
    sessionKey: sessionKey,
    senderId: senderId,
    senderName: senderName,
    conversationId: conversationId,
    channelId: channelId,
    chatType: chatType,
    capturedAt: Date.now(),
  };
}

function extractToolProvenanceFromHookEvent(event) {
  var context = event?.context ?? {};
  var payload = event?.payload ?? {};
  var params = event?.params ?? {};
  var tool = event?.tool ?? {};
  var toolCall = event?.toolCall ?? event?.tool_call ?? {};
  var call = event?.call ?? {};
  var session = event?.session ?? {};

  var sessionKey = firstNonEmpty(
    event?.sessionKey,
    context?.sessionKey,
    session?.key,
  );

  if (!sessionKey) return null;

  var toolName = firstNonEmpty(
    event?.toolName,
    tool?.name,
    toolCall?.name,
    call?.toolName,
    payload?.toolName,
    payload?.name,
    params?.toolName,
    params?.name,
  );

  var toolCallId = firstNonEmpty(
    event?.toolCallId,
    event?.tool_call_id,
    toolCall?.id,
    call?.id,
    payload?.toolCallId,
    payload?.callId,
    params?.toolCallId,
    params?.callId,
  );

  return {
    sessionKey: sessionKey,
    toolName: toolName,
    toolCallId: toolCallId,
  };
}

function toolHookEventHasError(event) {
  return Boolean(
    event?.error ||
    event?.payload?.error ||
    event?.result?.error ||
    event?.toolCall?.error ||
    event?.tool_call?.error
  );
}

function ensureToolProvenanceTurn(store, sessionKey) {
  var key = asString(sessionKey);
  if (!store || !key) return null;

  var existing = store.activeBySession.get(key);
  if (existing) return existing;

  var turn = {
    sessionKey: key,
    createdAt: Date.now(),
    updatedAt: Date.now(),
    attemptedTools: [],
    completedTools: [],
    failedTools: [],
    toolNamesByCallId: new Map(),
    executeSqlAttempted: false,
    executeSqlCompleted: false,
    incomplete: false,
  };
  store.activeBySession.set(key, turn);
  pruneToolProvenanceStore(store);
  return turn;
}

function recordToolProvenanceHookEvent(store, event, phase) {
  var info = extractToolProvenanceFromHookEvent(event);
  if (!info?.sessionKey) return null;

  var turn = ensureToolProvenanceTurn(store, info.sessionKey);
  if (!turn) return null;

  turn.updatedAt = Date.now();
  turn.lastPhase = asString(phase);

  if (phase === "before_tool_call") {
    if (!info.toolName) {
      turn.incomplete = true;
      return turn;
    }
    pushUnique(turn.attemptedTools, info.toolName);
    if (info.toolCallId) {
      turn.toolNamesByCallId.set(info.toolCallId, info.toolName);
    }
    if (info.toolName === "execute_sql") {
      turn.executeSqlAttempted = true;
    }
    return turn;
  }

  if (phase === "after_tool_call") {
    var resolvedToolName = info.toolName;
    if (!resolvedToolName && info.toolCallId) {
      resolvedToolName = asString(turn.toolNamesByCallId.get(info.toolCallId));
    }
    if (!resolvedToolName) {
      turn.incomplete = true;
      return turn;
    }
    if (toolHookEventHasError(event)) {
      pushUnique(turn.failedTools, resolvedToolName);
      return turn;
    }
    pushUnique(turn.completedTools, resolvedToolName);
    if (resolvedToolName === "execute_sql") {
      turn.executeSqlCompleted = true;
    }
  }

  return turn;
}

function archiveToolProvenanceTurn(store, sessionKey) {
  var key = asString(sessionKey);
  if (!store || !key) return null;

  var turn = store.activeBySession.get(key);
  if (!turn) return null;

  var completedTools = Array.isArray(turn.completedTools) ? turn.completedTools.slice() : [];
  var attemptedTools = Array.isArray(turn.attemptedTools) ? turn.attemptedTools.slice() : [];
  var tools = completedTools.length > 0 ? completedTools : attemptedTools;
  var status = "grounded";

  if (tools.length === 0) {
    status = "no_tools";
  } else if (completedTools.length === 0 || turn.incomplete) {
    status = "partial";
  }

  var snapshot = {
    sessionKey: key,
    tools: tools,
    pathKind: tools.length <= 1 ? "single_tool" : "multi_tool",
    executeSqlUsed: Boolean(turn.executeSqlCompleted),
    executeSqlAttempted: Boolean(turn.executeSqlAttempted),
    status: status,
    archivedAt: Date.now(),
  };

  store.lastBySession.set(key, snapshot);
  store.activeBySession.delete(key);
  pruneToolProvenanceStore(store);
  return snapshot;
}

function getLastToolProvenanceTurn(store, sessionKey) {
  var key = asString(sessionKey);
  if (!store || !key) return null;
  pruneToolProvenanceStore(store);
  return store.lastBySession.get(key) ?? null;
}

function clearToolProvenance(sessionKey) {
  var key = asString(sessionKey);
  if (!key) return;
  TOOL_PROVENANCE_STORE.activeBySession.delete(key);
  TOOL_PROVENANCE_STORE.lastBySession.delete(key);
}

function buildToolProvenancePromptAdditions(provenance) {
  if (!provenance || typeof provenance !== "object") return null;

  var tools = Array.isArray(provenance.tools)
    ? provenance.tools.filter(function (toolName) { return asString(toolName); })
    : [];
  var status = firstNonEmpty(provenance.status, "partial");
  var pathKind = firstNonEmpty(
    provenance.pathKind,
    tools.length <= 1 ? "single_tool" : "multi_tool",
  );
  var toolSummary = tools.length > 0 ? tools.join(", ") : "none";
  var appendLines = [
    "Methodology provenance for the immediately previous assistant answer:",
    "- If the user asks how you checked, mention only the actual recorded tools below.",
  ];

  if (status === "grounded") {
    appendLines.push("- The runtime provenance is grounded enough for a factual high-level explanation.");
  } else if (status === "no_tools") {
    appendLines.push("- The immediately previous assistant answer did not record any MCP tool calls.");
  } else {
    appendLines.push("- The runtime provenance is partial. Say the recorded tool path is partial instead of inventing missing steps.");
  }

  if (provenance.executeSqlUsed) {
    appendLines.push("- SQL was actually executed in the immediately previous answer.");
  } else {
    appendLines.push("- SQL was not actually executed in the immediately previous answer.");
  }

  if (provenance.executeSqlAttempted && !provenance.executeSqlUsed) {
    appendLines.push("- If asked, do not claim SQL as a completed data source for that answer.");
  }

  return {
    appendSystemContext: appendLines.join("\n"),
    prependContext: [
      "Last assistant answer provenance:",
      "- last_turn_tools: " + toolSummary,
      "- last_turn_path: " + (status === "no_tools" ? "none" : pathKind),
      "- last_turn_execute_sql: " + (provenance.executeSqlUsed ? "yes" : "no"),
      "- last_turn_provenance_status: " + status,
    ].join("\n"),
  };
}

function mergePromptAdditions(parts) {
  var prepend = [];
  var append = [];

  for (var i = 0; i < parts.length; i++) {
    var part = parts[i];
    if (!part || typeof part !== "object") continue;
    var prependText = asString(part.prependContext);
    var appendText = asString(part.appendSystemContext);
    if (prependText) prepend.push(prependText);
    if (appendText) append.push(appendText);
  }

  if (prepend.length === 0 && append.length === 0) return null;

  return {
    prependContext: prepend.join("\n\n"),
    appendSystemContext: append.join("\n\n"),
  };
}

function buildSpeakerPromptAdditions(speakerContext, cfg) {
  var primaryUserId = firstNonEmpty(cfg?.primaryUserId, "564550211");
  var primaryUserName = firstNonEmpty(cfg?.primaryUserName, "Leo");
  var primaryUserNameLower = primaryUserName.toLowerCase();
  var senderId = asString(speakerContext?.senderId);
  var senderName = asString(speakerContext?.senderName);
  var senderNameLower = senderName.toLowerCase();
  var chatType = firstNonEmpty(speakerContext?.chatType, "unknown");
  var conversationId = asString(speakerContext?.conversationId);
  var isLeo = Boolean(
    (senderId && senderId === primaryUserId) ||
    (!senderId && senderName && senderNameLower === primaryUserNameLower)
  );
  var preferredName = isLeo ? primaryUserName : senderName;
  var staticLines = [
    "Addressing policy for this turn:",
    "- This assistant is not Leo-exclusive.",
    "- Never default unknown people to Leo.",
    "- Only call the user \"" + primaryUserName + "\" when the current speaker is clearly " + primaryUserName + " (preferred id: " + primaryUserId + ").",
    "- For any other direct chat or group speaker, use the current speaker's nickname/display name when available.",
    "- If the current speaker name is unavailable or uncertain, reply naturally without forcing a name.",
  ];
  var dynamicLines = [
    "Current speaker context:",
    "- chat_type: " + chatType,
    "- sender_id: " + (senderId || "(unknown)"),
    "- sender_name: " + (senderName || "(unknown)"),
    "- conversation_id: " + (conversationId || "(unknown)"),
  ];

  if (preferredName) {
    dynamicLines.push("- preferred_salutation: " + preferredName);
  } else {
    dynamicLines.push("- preferred_salutation: none");
  }

  if (isLeo) {
    dynamicLines.push("- current_speaker_is_primary_operator: yes");
  } else {
    dynamicLines.push("- current_speaker_is_primary_operator: no");
  }

  return {
    appendSystemContext: staticLines.join("\n"),
    prependContext: dynamicLines.join("\n"),
  };
}

function rememberSpeakerContext(event) {
  var speakerContext = extractSpeakerContextFromMessageEvent(event);
  if (!speakerContext?.sessionKey) return null;
  SPEAKER_CONTEXT_BY_SESSION.set(speakerContext.sessionKey, speakerContext);
  pruneSpeakerContextStore();
  return speakerContext;
}

function clearSpeakerContext(sessionKey) {
  var key = asString(sessionKey);
  if (!key) return;
  SPEAKER_CONTEXT_BY_SESSION.delete(key);
}

function registerHookCompat(api, name, handler, log) {
  if (typeof api?.registerHook === "function") {
    try {
      api.registerHook(name, handler);
      return true;
    } catch (_err) {
      try {
        api.registerHook({ name: name, execute: handler });
        return true;
      } catch (_err2) {
      }
    }
  }

  if (typeof api?.on === "function") {
    try {
      api.on(name, handler);
      return true;
    } catch (_err3) {
    }
  }

  log?.warn?.("[mcp-products] unable to register hook " + name + " on this OpenClaw runtime");
  return false;
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

function safeJsonParse(text) {
  try {
    return JSON.parse(text);
  } catch (_err) {
    return null;
  }
}

function extractStructuredToolData(mcpResult) {
  var structured = mcpResult?.structuredContent ?? mcpResult?.structured_content ?? null;

  if (structured && typeof structured === "object" && typeof structured.result === "string" && Object.keys(structured).length === 1) {
    var parsedStructured = safeJsonParse(structured.result);
    if (parsedStructured && typeof parsedStructured === "object") {
      structured = parsedStructured;
    }
  }

  if (structured && typeof structured === "object" && !Array.isArray(structured)) {
    return structured;
  }

  if (!Array.isArray(mcpResult?.content)) return null;

  for (var i = 0; i < mcpResult.content.length; i++) {
    var block = mcpResult.content[i];
    if (block?.type !== "text") continue;
    var parsed = safeJsonParse(block.text);
    if (parsed && typeof parsed === "object") {
      return parsed;
    }
  }

  return null;
}

function formatMoney(value) {
  if (typeof value !== "number" || !Number.isFinite(value)) return "未知";
  return "$" + value.toFixed(2);
}

function formatRating(value) {
  if (typeof value !== "number" || !Number.isFinite(value)) return "未知";
  return value.toFixed(1) + "/5";
}

function siteLabel(value) {
  var key = lower(value);
  if (key === "basspro") return "Bass Pro";
  if (key === "meatyourmaker") return "MYM";
  if (key === "waltons") return "Walton's";
  return asString(value) || "未知";
}

function ownershipLabel(value) {
  var key = lower(value);
  if (key === "own") return "自有";
  if (key === "competitor") return "竞品";
  return asString(value) || "未知";
}

function formatCountBreakdown(items, preferredKeys, labeler) {
  if (!items || typeof items !== "object") return "";

  var seen = new Set();
  var parts = [];
  var keys = [];

  if (Array.isArray(preferredKeys)) {
    for (var i = 0; i < preferredKeys.length; i++) {
      if (Object.prototype.hasOwnProperty.call(items, preferredKeys[i])) {
        keys.push(preferredKeys[i]);
        seen.add(preferredKeys[i]);
      }
    }
  }

  var extraKeys = Object.keys(items)
    .filter(function (key) { return !seen.has(key); })
    .sort();
  keys = keys.concat(extraKeys);

  for (var j = 0; j < keys.length; j++) {
    var key = keys[j];
    var count = items[key];
    if (typeof count !== "number" || !Number.isFinite(count)) continue;
    parts.push(labeler(key) + " " + count + " 个");
  }

  return parts.join("；");
}

function summarizeStats(data) {
  var lines = [
    "## 数据概览",
    "",
    "- **产品总数**：" + (data.total_products ?? "未知"),
    "- **已入库评论数**：" + (data.total_reviews ?? "未知"),
    "- **平均价格**：" + formatMoney(data.avg_price),
    "- **平均评分**：" + formatRating(data.avg_rating),
  ];

  if (data.last_scrape_at) {
    lines.push("- **最后更新**：" + data.last_scrape_at);
  }

  var ownershipBreakdown = formatCountBreakdown(
    data.by_ownership,
    ["own", "competitor"],
    ownershipLabel,
  );
  var siteBreakdown = formatCountBreakdown(
    data.by_site,
    ["basspro", "meatyourmaker", "waltons"],
    siteLabel,
  );

  if (ownershipBreakdown || siteBreakdown) {
    lines.push("", "### 分布");
    if (ownershipBreakdown) {
      lines.push("- **归属**：" + ownershipBreakdown);
    }
    if (siteBreakdown) {
      lines.push("- **站点**：" + siteBreakdown);
    }
  }

  return lines.join("\n");
}

function summarizeProductList(data) {
  var total = data?.total ?? 0;
  var items = Array.isArray(data?.items) ? data.items : [];
  var lines = [
    "## 搜索结果",
    "",
    "- **命中产品数**：" + total,
  ];

  if (items.length === 0) {
    lines.push("- 当前条件下没有匹配产品。");
    return lines.join("\n");
  }

  var shown = items.slice(0, 5);
  lines.push("", "### 示例产品");
  for (var i = 0; i < shown.length; i++) {
    var item = shown[i] ?? {};
    lines.push(
      (i + 1) + ". **" + (item.name || "未命名产品") + "**" +
      " · " + siteLabel(item.site) +
      " · " + ownershipLabel(item.ownership) +
      " · " + formatMoney(item.price) +
      " · " + formatRating(item.rating) +
      " · 站点评论 " + (item.review_count ?? 0) + " 条"
    );
  }

  if (total > shown.length) {
    lines.push("", "- 其余 " + (total - shown.length) + " 个结果可继续展开。");
  }

  return lines.join("\n");
}

function summarizeProductDetail(data) {
  var lines = [
    "## 产品详情",
    "",
    "### " + (data.name || "未命名产品"),
    "- **SKU**：" + (data.sku || "未知"),
    "- **站点**：" + siteLabel(data.site),
    "- **归属**：" + ownershipLabel(data.ownership),
    "- **价格**：" + formatMoney(data.price),
    "- **评分**：" + formatRating(data.rating),
    "- **站点展示评论总数**：" + (data.review_count ?? 0),
  ];

  if (Array.isArray(data.recent_reviews) && data.recent_reviews.length > 0) {
    lines.push("", "- **最近评论样本**：" + data.recent_reviews.length + " 条");
  }

  return lines.join("\n");
}

function summarizeReviewList(data) {
  var total = data?.total ?? 0;
  var items = Array.isArray(data?.items) ? data.items : [];
  var lines = [
    "## 评论结果",
    "",
    "- **命中评论数**：" + total,
  ];

  if (items.length === 0) {
    lines.push("- 当前条件下没有匹配评论。");
    return lines.join("\n");
  }

  var shown = items.slice(0, 3);
  lines.push("", "### 评论样本");
  for (var i = 0; i < shown.length; i++) {
    var item = shown[i] ?? {};
    lines.push(
      (i + 1) + ". **" + (item.product_name || item.name || "未知产品") + "**" +
      " · " + formatRating(item.rating) +
      " · " + (item.author || "匿名")
    );
  }

  if (total > shown.length) {
    lines.push("", "- 其余 " + (total - shown.length) + " 条评论可继续展开。");
  }

  return lines.join("\n");
}

function summarizePreviewScope(data) {
  var counts = data?.counts ?? {};
  var artifactType = data?.artifact_type || "report";
  var hint = data?.next_action_hint || "unknown";
  return [
    "Preview scope (" + artifactType + "): " +
      (counts.products ?? "unknown") + " products, " +
      (counts.reviews ?? "unknown") + " reviews, " +
      (counts.image_reviews ?? "unknown") + " image reviews.",
    "Next action: " + hint + ".",
  ].join("\n");
}

function summarizeSendFilteredReport(data) {
  var stats = data?.data ?? {};
  var artifact = data?.artifact ?? {};
  var email = data?.email ?? null;
  var lines = [
    "Filtered report result:",
    "- products: " + (stats.products_count ?? "unknown"),
    "- reviews: " + (stats.reviews_count ?? "unknown"),
    "- artifact: " + (artifact.success ? "success" : "failed"),
  ];

  if (artifact.excel_path) {
    lines.push("- file: " + artifact.excel_path);
  }

  if (email) {
    lines.push(
      "- email: " +
      (email.success ? "success" : "failed") +
      " (" + (email.recipients ?? 0) + " recipients)"
    );
  } else {
    lines.push("- email: not requested");
  }

  return lines.join("\n");
}

function summarizeExportReviewImages(data) {
  var stats = data?.data ?? {};
  var artifact = data?.artifact ?? {};
  var items = Array.isArray(artifact.items) ? artifact.items : [];
  var sampleLinks = [];

  for (var i = 0; i < items.length && sampleLinks.length < 3; i++) {
    var row = items[i] ?? {};
    var images = Array.isArray(row.images) ? row.images : [];
    for (var j = 0; j < images.length && sampleLinks.length < 3; j++) {
      sampleLinks.push(images[j]);
    }
  }

  var lines = [
    "Review image export:",
    "- products: " + (stats.products_count ?? "unknown"),
    "- image reviews: " + (stats.image_reviews_count ?? "unknown"),
    "- image links: " + (stats.image_links_count ?? "unknown"),
    "- artifact: " + (artifact.success ? "success" : "failed"),
  ];

  if (items.length > 0) {
    lines.push("- sample product: " + (items[0].product_name || "unknown"));
  }

  for (var k = 0; k < sampleLinks.length; k++) {
    lines.push("- link " + (k + 1) + ": " + sampleLinks[k]);
  }

  return lines.join("\n");
}

function summarizeWorkflowStatus(data) {
  var run = data?.run ?? {};
  var tasks = Array.isArray(data?.tasks) ? data.tasks : [];
  return [
    "## Workflow 状态",
    "",
    "- **状态**：" + (run.status || "未知"),
    "- **报告阶段**：" + (run.report_phase || "未知"),
    "- **报告产物**：" + (run.report_generation_status || "未知"),
    "- **业务邮件**：" + (run.email_delivery_status || "未知"),
    "- **workflow 通知**：" + (run.workflow_notification_status || "未知"),
    "- **最近投递错误**：" + (run.delivery_last_error || "无"),
    "- **触发键**：" + (run.trigger_key || run.id || "未知"),
    "- **关联任务数**：" + tasks.length,
  ].join("\n");
}

function summarizePendingNotifications(data) {
  var total = data?.total ?? 0;
  var items = Array.isArray(data?.items) ? data.items : [];
  var lines = [
    "## 通知投递状态",
    "",
    "- **通知记录数**：" + total,
  ];

  var shown = items.slice(0, 5);
  for (var i = 0; i < shown.length; i++) {
    var item = shown[i] ?? {};
    lines.push(
      "- **" + (item.kind || "unknown") + "**：" +
      (item.status || "未知") +
      (item.last_error ? "（" + item.last_error + "）" : "")
    );
  }

  return lines.join("\n");
}

function summarizeStructuredToolResult(toolName, data) {
  if (!data || typeof data !== "object") return "";
  if (data.error) return "工具返回错误： " + data.error;

  if (toolName === "get_stats") return summarizeStats(data);
  if (toolName === "list_products") return summarizeProductList(data);
  if (toolName === "get_product_detail") return summarizeProductDetail(data);
  if (toolName === "query_reviews") return summarizeReviewList(data);
  if (toolName === "preview_scope") return summarizePreviewScope(data);
  if (toolName === "send_filtered_report") return summarizeSendFilteredReport(data);
  if (toolName === "export_review_images") return summarizeExportReviewImages(data);
  if (toolName === "get_workflow_status") return summarizeWorkflowStatus(data);
  if (toolName === "list_pending_notifications") return summarizePendingNotifications(data);

  if (Array.isArray(data.items) && typeof data.total !== "undefined") {
    return "已获得结构化结果，共 " + data.total + " 条。请整理后再回复用户，不要直接回显原始字段。";
  }

  return "已获得结构化结果。请基于关键字段整理最终回复，不要直接回显原始 JSON。";
}

function normalizeMcpToolResult(toolName, mcpResult) {
  var structured = extractStructuredToolData(mcpResult);
  if (structured) {
    var missingFields = missingRequiredCanonicalFields(toolName, structured);
    var summaryText = missingFields.length > 0
      ? "Structured result missing required canonical fields for " + toolName + ": " + missingFields.join(", ")
      : summarizeStructuredToolResult(toolName, structured);
    return {
      content: [{ type: "text", text: summaryText }],
      details: { ...(mcpResult ?? {}), structuredContent: structured },
    };
  }

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

var LEGACY_TOOL_DEFINITIONS = [
  {
    name: "start_scrape",
    description: "Submit product URLs for scraping. Params: urls (array of URL strings), ownership (required: 'own' or 'competitor'), review_limit (optional int; first successful scrape stays full, later scrapes can be limited).",
    parameters: {
      type: "object",
      properties: {
        urls: { type: "array", items: { type: "string" }, description: "Product page URLs to scrape" },
        ownership: { type: "string", description: "Product ownership: 'own' or 'competitor'" },
        review_limit: { type: "integer", description: "Optional review cap for repeat scrapes. First successful scrape still runs full. Use 0 for full." },
        reply_to: { type: "string", description: "Notification target when task completes. Pass the OriginatingTo value from the current message (format: user:{id} or chat:{id}). Fallback: chat:cidoOQUuAEydsdghncIE5INqg==" }
      },
      required: ["urls", "ownership", "reply_to"]
    }
  },
  {
    name: "start_collect",
    description: "Collect products from a category page then scrape each. Params: category_url (string), ownership (required: 'own' or 'competitor'), max_pages (int, 0=all), review_limit (optional int for repeat scrapes only).",
    parameters: {
      type: "object",
      properties: {
        category_url: { type: "string", description: "Category page URL" },
        ownership: { type: "string", description: "Product ownership: 'own' or 'competitor'" },
        max_pages: { type: "integer", description: "Max pages to collect, 0 for all" },
        review_limit: { type: "integer", description: "Optional review cap for already-known product URLs discovered from the category. New URLs still run full. Use 0 for full." },
        reply_to: { type: "string", description: "Notification target when task completes. Pass the OriginatingTo value from the current message (format: user:{id} or chat:{id}). Fallback: chat:cidoOQUuAEydsdghncIE5INqg==" }
      },
      required: ["category_url", "ownership", "reply_to"]
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
    description: "Search and filter scraped products. All params optional: site (basspro/meatyourmaker/waltons), search (keyword), min_price, max_price, stock_status, sort_by, order, limit, offset.",
    parameters: {
      type: "object",
      properties: {
        site: { type: "string", description: "Site filter: basspro, meatyourmaker, or waltons" },
        search: { type: "string", description: "Product name keyword search" },
        min_price: { type: "number", description: "Min price filter (USD), -1 to skip" },
        max_price: { type: "number", description: "Max price filter (USD), -1 to skip" },
        stock_status: { type: "string", description: "Stock status: in_stock, out_of_stock, unknown" },
        ownership: { type: "string", description: "Ownership filter: own or competitor" },
        sort_by: { type: "string", description: "Sort field: price, rating, review_count, scraped_at, name" },
        order: { type: "string", description: "Sort direction: asc or desc" },
        limit: { type: "integer", description: "Page size, default 20" },
        offset: { type: "integer", description: "Pagination offset, default 0" }
      }
    }
  },
  {
    name: "get_product_detail",
    description: "Get full product info with recent reviews and price snapshots. Accepts ONLY these parameters: product_id, url, or sku (provide one). No site filter — SKU lookup is cross-site.",
    parameters: {
      type: "object",
      properties: {
        product_id: { type: "integer", description: "Product ID, -1 to skip" },
        url: { type: "string", description: "Product page URL" },
        sku: { type: "string", description: "Product SKU" }
      },
      additionalProperties: false
    }
  },
  {
    name: "query_reviews",
    description: "Query product reviews with filters. All params optional: product_id, site, min_rating, max_rating, author, keyword, has_images, sort_by, order, limit, offset.",
    parameters: {
      type: "object",
      properties: {
        product_id: { type: "integer", description: "Filter by product ID, -1 to skip" },
        sku: { type: "string", description: "Filter by product SKU" },
        site: { type: "string", description: "Site filter: basspro, meatyourmaker, or waltons" },
        ownership: { type: "string", description: "Ownership filter: own or competitor" },
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
    name: "preview_scope",
    description: "Preview a normalized reporting scope and return matched counts plus the next-action hint. Params: products, reviews, window, artifact_type (default report). Product filters support ids, urls, skus, names, sites, ownership, price, rating, review_count. Does not generate files or send email.",
    parameters: {
      type: "object",
      properties: {
        products: { type: "object", description: "Product scope filters: ids, urls, skus, names, sites, ownership, price, rating, review_count" },
        reviews: { type: "object", description: "Review scope filters: sentiment, rating, keyword, has_images" },
        window: { type: "object", description: "Window filters: since, until" },
        artifact_type: { type: "string", description: "Artifact type: report or review_images. Default report.", default: "report" }
      }
    }
  },
  {
    name: "send_filtered_report",
    description: "Generate a filtered report for a normalized scope and optionally deliver it by email. Params: scope (products/reviews/window), delivery (format, recipients, output_path, subject). Product filters support ids, urls, skus, names, sites, ownership, price, rating, review_count. Preserves the legacy email/report contract by default.",
    parameters: {
      type: "object",
      properties: {
        scope: { type: "object", description: "Normalized scope object with products, reviews, and window filters." },
        delivery: { type: "object", description: "Delivery options: format (excel/email), recipients, output_path, subject." }
      }
    }
  },
  {
    name: "export_review_images",
    description: "Export review-image links for a normalized scope. Review images only; returns links/manifest data only, no zip packaging or product hero images.",
    parameters: {
      type: "object",
      properties: {
        scope: { type: "object", description: "Normalized scope object with products, reviews, and window filters." },
        limit: { type: "integer", description: "Maximum number of image-bearing review rows to include. Default 20." }
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
    description: "Execute read-only SQL on the crawler database. Only SELECT allowed, max 500 rows, 5s timeout. Tables include products, product_snapshots, reviews, tasks, workflow_runs, workflow_run_tasks, and notification_outbox.",
    parameters: {
      type: "object",
      properties: {
        sql: { type: "string", description: "SELECT SQL query" }
      },
      required: ["sql"]
    }
  },
  {
    name: "generate_report",
    description: "Generate scrape report: query new data since timestamp, translate reviews to Chinese, generate Excel, send email. Returns summary with counts and email status.",
    parameters: {
      type: "object",
      properties: {
        since: { type: "string", description: "Shanghai timestamp (YYYY-MM-DDTHH:MM:SS), query data after this time" },
        send_email: { type: "string", description: "Send email with report: 'true' or 'false', default 'true'" }
      },
      required: ["since"]
    }
  },
  {
    name: "trigger_translate",
    description: "Manually trigger translation worker to process untranslated reviews. reset_skipped='true' resets all skipped reviews back to pending (for re-translating historical data).",
    parameters: {
      type: "object",
      properties: {
        reset_skipped: { type: "string", description: "Reset skipped reviews to pending: 'true' or 'false', default 'false'" }
      }
    }
  },
  {
    name: "get_translate_status",
    description: "Query translation progress: total reviews, translated, pending, failed, skipped counts. Optionally filter by time range.",
    parameters: {
      type: "object",
      properties: {
        since: { type: "string", description: "Shanghai timestamp (YYYY-MM-DDTHH:MM:SS), only count reviews after this time. Empty for all." }
      }
    }
  },
  {
    name: "get_workflow_status",
    description: "Get one daily workflow run plus its child collect/scrape task records. Provide either run_id or trigger_key (for example daily:2026-03-31).",
    parameters: {
      type: "object",
      properties: {
        run_id: { type: "string", description: "Workflow run ID. Empty when querying by trigger_key." },
        trigger_key: { type: "string", description: "Workflow trigger key, e.g. daily:2026-03-31" }
      }
    }
  },
  {
    name: "list_workflow_runs",
    description: "List daily workflow runs, optionally filtered by status. Use this to inspect submitted/running/reporting/completed/needs_attention runs.",
    parameters: {
      type: "object",
      properties: {
        status: { type: "string", description: "Optional status filter: submitted, running, reporting, completed, needs_attention. Empty for all." },
        limit: { type: "integer", description: "Max number of workflow runs to return, default 20" }
      }
    }
  },
  {
    name: "list_pending_notifications",
    description: "List notification outbox records, optionally filtered by status. Use this to inspect workflow_started, workflow_fast_report, workflow_full_report, workflow_attention, and task_completed deliveries.",
    parameters: {
      type: "object",
      properties: {
        status: { type: "string", description: "Optional outbox status filter: pending, claimed, sent, failed, deadletter. Empty for all." },
        limit: { type: "integer", description: "Max number of notification rows to return, default 20" }
      }
    }
  }
];

var CONTRACT_TOOLS = CONTRACT_TOOL_ORDER.map(contractToolToPluginTool);
var CONTRACT_TOOL_BY_NAME = new Map(
  CONTRACT_TOOLS.map(function (tool) {
    return [tool.name, tool];
  }),
);
var LOCAL_ONLY_TOOL_NAMES = LEGACY_TOOL_DEFINITIONS
  .filter(function (tool) {
    return !CONTRACT_TOOL_NAME_SET.has(tool.name);
  })
  .map(function (tool) {
    return tool.name;
  });
var TOOLS = LEGACY_TOOL_DEFINITIONS.map(function (tool) {
  return CONTRACT_TOOL_BY_NAME.get(tool.name) || tool;
});

for (var contractIndex = 0; contractIndex < CONTRACT_TOOLS.length; contractIndex++) {
  var contractTool = CONTRACT_TOOLS[contractIndex];
  var exists = TOOLS.some(function (tool) {
    return tool.name === contractTool.name;
  });
  if (!exists) {
    TOOLS.push(contractTool);
  }
}

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
      primaryUserId: { type: "string" },
      primaryUserName: { type: "string" },
      addressingContextEnabled: { type: "boolean" },
    },
    required: ["endpoint"],
    additionalProperties: false,
  },

  register(api) {
    var cfg = getCfg(api);
    var endpoint = cfg.endpoint;
    var protocolVersion = cfg.protocolVersion || "2025-03-26";
    var timeoutMs = Number.isFinite(cfg.timeoutMs) ? cfg.timeoutMs : 60000;
    var log = api.logger ?? console;
    var addressingContextEnabled = cfg.addressingContextEnabled !== false;

    if (!endpoint) {
      throw new Error("mcp-products plugin requires config.endpoint");
    }

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
            return normalizeMcpToolResult(t.name, result);
          },
        });
      })(tool);
    }

    registerHookCompat(api, "message_received", async function (event) {
      var sessionKey = firstNonEmpty(event?.sessionKey, event?.context?.sessionKey);
      archiveToolProvenanceTurn(TOOL_PROVENANCE_STORE, sessionKey);
      if (addressingContextEnabled) {
        rememberSpeakerContext(event);
      }
    }, log);

    registerHookCompat(api, "before_prompt_build", async function (event) {
      var sessionKey = firstNonEmpty(event?.sessionKey, event?.context?.sessionKey);
      var additions = [];

      if (sessionKey) {
        ensureToolProvenanceTurn(TOOL_PROVENANCE_STORE, sessionKey);
        var provenance = getLastToolProvenanceTurn(TOOL_PROVENANCE_STORE, sessionKey);
        var provenanceAdditions = buildToolProvenancePromptAdditions(provenance);
        if (provenanceAdditions) {
          additions.push(provenanceAdditions);
        }
      }

      if (addressingContextEnabled) {
        var speakerContext = SPEAKER_CONTEXT_BY_SESSION.get(sessionKey);

        if (!speakerContext) {
          speakerContext = rememberSpeakerContext(event);
        }

        if (speakerContext) {
          additions.push(buildSpeakerPromptAdditions(speakerContext, cfg));
        }
      }

      return mergePromptAdditions(additions);
    }, log);

    registerHookCompat(api, "before_tool_call", async function (event) {
      recordToolProvenanceHookEvent(TOOL_PROVENANCE_STORE, event, "before_tool_call");
    }, log);

    registerHookCompat(api, "after_tool_call", async function (event) {
      recordToolProvenanceHookEvent(TOOL_PROVENANCE_STORE, event, "after_tool_call");
    }, log);

    registerHookCompat(api, "before_reset", async function (event) {
      var sessionKey = firstNonEmpty(event?.sessionKey, event?.context?.sessionKey);
      clearSpeakerContext(sessionKey);
      clearToolProvenance(sessionKey);
    }, log);

    registerHookCompat(api, "session_end", async function (event) {
      var sessionKey = firstNonEmpty(event?.sessionKey, event?.context?.sessionKey);
      clearSpeakerContext(sessionKey);
      clearToolProvenance(sessionKey);
    }, log);

    log.info?.("[mcp-products] registered " + TOOLS.length + " MCP tools against " + endpoint);
  },
};

export {
  archiveToolProvenanceTurn,
  buildSpeakerPromptAdditions,
  buildToolProvenancePromptAdditions,
  CONTRACT_TOOL_NAMES,
  createToolProvenanceStore,
  ensureToolProvenanceTurn,
  extractSpeakerContextFromMessageEvent,
  extractToolProvenanceFromHookEvent,
  LOCAL_ONLY_TOOL_NAMES,
  normalizeMcpToolResult,
  recordToolProvenanceHookEvent,
  TOOL_CONTRACT_ARTIFACT,
};
