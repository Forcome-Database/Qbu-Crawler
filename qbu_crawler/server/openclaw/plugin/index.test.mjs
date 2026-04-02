import assert from "node:assert/strict";
import plugin, {
  archiveToolProvenanceTurn,
  buildSpeakerPromptAdditions,
  buildToolProvenancePromptAdditions,
  CONTRACT_TOOL_NAMES,
  createToolProvenanceStore,
  ensureToolProvenanceTurn,
  extractToolProvenanceFromHookEvent,
  LOCAL_ONLY_TOOL_NAMES,
  extractSpeakerContextFromMessageEvent,
  normalizeMcpToolResult,
  recordToolProvenanceHookEvent,
  TOOL_CONTRACT_ARTIFACT,
} from "./index.js";

function testExtractSpeakerContextFromMessageEvent() {
  const speaker = extractSpeakerContextFromMessageEvent({
    sessionKey: "agent:main:dingtalk:group:cido123",
    context: {
      channelId: "dingtalk",
      conversationId: "cido123",
      metadata: {
        chatType: "group",
        senderId: "9988",
        senderName: "张三",
      },
    },
  });

  assert.equal(speaker.sessionKey, "agent:main:dingtalk:group:cido123");
  assert.equal(speaker.chatType, "group");
  assert.equal(speaker.senderId, "9988");
  assert.equal(speaker.senderName, "张三");
  assert.equal(speaker.conversationId, "cido123");
}

function testBuildSpeakerPromptAdditionsForLeo() {
  const prompt = buildSpeakerPromptAdditions(
    {
      senderId: "564550211",
      senderName: "Leo",
      chatType: "direct",
      conversationId: "cid-1",
    },
    {
      primaryUserId: "564550211",
      primaryUserName: "Leo",
    },
  );

  assert.match(prompt.appendSystemContext, /not Leo-exclusive/i);
  assert.match(prompt.prependContext, /preferred_salutation: Leo/);
  assert.match(prompt.prependContext, /current_speaker_is_primary_operator: yes/);
}

function testBuildSpeakerPromptAdditionsForOtherSpeaker() {
  const prompt = buildSpeakerPromptAdditions(
    {
      senderId: "7788",
      senderName: "王五",
      chatType: "group",
      conversationId: "cid-2",
    },
    {
      primaryUserId: "564550211",
      primaryUserName: "Leo",
    },
  );

  assert.match(prompt.prependContext, /sender_name: 王五/);
  assert.match(prompt.prependContext, /preferred_salutation: 王五/);
  assert.match(prompt.prependContext, /current_speaker_is_primary_operator: no/);
  assert.doesNotMatch(prompt.prependContext, /preferred_salutation: Leo/);
}

function testExtractToolProvenanceFromHookEvent() {
  const provenance = extractToolProvenanceFromHookEvent({
    context: { sessionKey: "agent:main:dingtalk:group:cido123" },
    tool: { name: "get_stats" },
    toolCall: { id: "call-1" },
  });

  assert.equal(provenance.sessionKey, "agent:main:dingtalk:group:cido123");
  assert.equal(provenance.toolName, "get_stats");
  assert.equal(provenance.toolCallId, "call-1");
}

function testToolProvenanceSingleToolGrounded() {
  const store = createToolProvenanceStore();

  ensureToolProvenanceTurn(store, "session-1");
  recordToolProvenanceHookEvent(
    store,
    {
      sessionKey: "session-1",
      tool: { name: "get_stats" },
      toolCall: { id: "call-1" },
    },
    "before_tool_call",
  );
  recordToolProvenanceHookEvent(
    store,
    {
      sessionKey: "session-1",
      tool: { name: "get_stats" },
      toolCall: { id: "call-1" },
    },
    "after_tool_call",
  );

  const archived = archiveToolProvenanceTurn(store, "session-1");
  const prompt = buildToolProvenancePromptAdditions(archived);

  assert.deepEqual(archived.tools, ["get_stats"]);
  assert.equal(archived.pathKind, "single_tool");
  assert.equal(archived.executeSqlUsed, false);
  assert.equal(archived.status, "grounded");
  assert.match(prompt.prependContext, /last_turn_tools: get_stats/);
  assert.match(prompt.prependContext, /last_turn_path: single_tool/);
  assert.match(prompt.prependContext, /last_turn_execute_sql: no/);
  assert.match(prompt.prependContext, /last_turn_provenance_status: grounded/);
}

function testToolProvenanceMultiToolAndSqlGrounded() {
  const store = createToolProvenanceStore();

  ensureToolProvenanceTurn(store, "session-2");
  for (const [callId, toolName] of [["call-1", "get_stats"], ["call-2", "list_products"], ["call-3", "execute_sql"]]) {
    recordToolProvenanceHookEvent(
      store,
      {
        sessionKey: "session-2",
        tool: { name: toolName },
        toolCall: { id: callId },
      },
      "before_tool_call",
    );
    recordToolProvenanceHookEvent(
      store,
      {
        sessionKey: "session-2",
        tool: { name: toolName },
        toolCall: { id: callId },
      },
      "after_tool_call",
    );
  }

  const archived = archiveToolProvenanceTurn(store, "session-2");
  const prompt = buildToolProvenancePromptAdditions(archived);

  assert.deepEqual(archived.tools, ["get_stats", "list_products", "execute_sql"]);
  assert.equal(archived.pathKind, "multi_tool");
  assert.equal(archived.executeSqlUsed, true);
  assert.equal(archived.status, "grounded");
  assert.match(prompt.prependContext, /last_turn_tools: get_stats, list_products, execute_sql/);
  assert.match(prompt.prependContext, /last_turn_path: multi_tool/);
  assert.match(prompt.prependContext, /last_turn_execute_sql: yes/);
}

function testToolProvenanceFallsBackToPartialWhenCompletionMissing() {
  const store = createToolProvenanceStore();

  ensureToolProvenanceTurn(store, "session-3");
  recordToolProvenanceHookEvent(
    store,
    {
      sessionKey: "session-3",
      tool: { name: "list_products" },
      toolCall: { id: "call-1" },
    },
    "before_tool_call",
  );

  const archived = archiveToolProvenanceTurn(store, "session-3");
  const prompt = buildToolProvenancePromptAdditions(archived);

  assert.deepEqual(archived.tools, ["list_products"]);
  assert.equal(archived.status, "partial");
  assert.match(prompt.prependContext, /last_turn_provenance_status: partial/);
  assert.match(prompt.appendSystemContext, /partial instead of inventing missing steps/i);
}

function testToolProvenanceForbidsClaimingSqlWhenOnlyAttempted() {
  const prompt = buildToolProvenancePromptAdditions({
    tools: ["get_stats", "execute_sql"],
    pathKind: "multi_tool",
    executeSqlUsed: false,
    executeSqlAttempted: true,
    status: "partial",
  });

  assert.match(prompt.appendSystemContext, /SQL was not actually executed/i);
  assert.match(prompt.appendSystemContext, /do not claim SQL as a completed data source/i);
  assert.match(prompt.prependContext, /last_turn_execute_sql: no/);
}

function testToolProvenanceNoToolsStaysGroundedToNoTools() {
  const prompt = buildToolProvenancePromptAdditions({
    tools: [],
    executeSqlUsed: false,
    executeSqlAttempted: false,
    status: "no_tools",
  });

  assert.match(prompt.appendSystemContext, /did not record any MCP tool calls/i);
  assert.match(prompt.prependContext, /last_turn_path: none/);
  assert.match(prompt.prependContext, /last_turn_provenance_status: no_tools/);
}

function testNormalizeMcpToolResultUsesStructuredStatsSummary() {
  const normalized = normalizeMcpToolResult("get_stats", {
    content: [{ type: "text", text: "{\"total_products\":41,\"total_reviews\":2570}" }],
    structuredContent: {
      product_count: 41,
      ingested_review_rows: 2570,
      site_reported_review_total_current: 3120,
      avg_price_current: 416.32,
      avg_rating_current: 4.52,
      total_products: 41,
      total_reviews: 2570,
      by_site: {
        basspro: 13,
        meatyourmaker: 13,
        waltons: 15,
      },
      by_ownership: {
        own: 13,
        competitor: 28,
      },
      avg_price: 416.32,
      avg_rating: 4.52,
      last_scrape_at: "2026-03-31 18:31:00",
      time_axes: {
        product_state_time: {
          field: "products.scraped_at",
          latest: "2026-03-31 18:31:00",
        },
      },
    },
  });

  assert.match(normalized.content[0].text, /数据概览/);
  assert.match(normalized.content[0].text, /产品总数/);
  assert.match(normalized.content[0].text, /已入库评论数/);
  assert.match(normalized.content[0].text, /Bass Pro/);
  assert.match(normalized.content[0].text, /Walton's/);
  assert.match(normalized.content[0].text, /自有/);
  assert.doesNotMatch(normalized.content[0].text, /^\s*\{/);
}

function testNormalizeMcpToolResultFailsClearlyWhenCanonicalStatsFieldsAreMissing() {
  const normalized = normalizeMcpToolResult("get_stats", {
    structuredContent: {
      avg_price: 416.32,
    },
  });

  assert.match(normalized.content[0].text, /missing required canonical fields/i);
  assert.match(normalized.content[0].text, /total_products/);
  assert.match(normalized.content[0].text, /total_reviews/);
}

function testNormalizeMcpToolResultParsesJsonTextForProductLists() {
  const normalized = normalizeMcpToolResult("list_products", {
    content: [{
      type: "text",
      text: "{\"items\":[{\"name\":\"16\\\" Meat Saw\",\"site\":\"meatyourmaker\",\"ownership\":\"competitor\",\"price\":44.99,\"rating\":4.5,\"review_count\":71}],\"total\":1}",
    }],
  });

  assert.match(normalized.content[0].text, /搜索结果/);
  assert.match(normalized.content[0].text, /16" Meat Saw/);
  assert.doesNotMatch(normalized.content[0].text, /^\s*\{/);
}

function testNormalizeMcpToolResultSummarizesPreviewScope() {
  const normalized = normalizeMcpToolResult("preview_scope", {
    structuredContent: {
      artifact_type: "report",
      scope: {},
      counts: {
        products: 12,
        reviews: 240,
        image_reviews: 18,
      },
      next_action_hint: "requires_confirmation",
    },
  });

  assert.match(normalized.content[0].text, /12/);
  assert.match(normalized.content[0].text, /240/);
  assert.match(normalized.content[0].text, /18/);
  assert.match(normalized.content[0].text, /requires_confirmation|需确认|确认/);
  assert.doesNotMatch(normalized.content[0].text, /^\s*\{/);
}

function testNormalizeMcpToolResultSummarizesSendFilteredReport() {
  const normalized = normalizeMcpToolResult("send_filtered_report", {
    structuredContent: {
      data: {
        products_count: 1,
        reviews_count: 3,
      },
      artifact: {
        success: true,
        format: "excel",
        excel_path: "./reports/filtered-report.xlsx",
      },
      email: {
        success: true,
        recipients: 1,
      },
    },
  });

  assert.match(normalized.content[0].text, /1/);
  assert.match(normalized.content[0].text, /3/);
  assert.match(normalized.content[0].text, /filtered-report\.xlsx/);
  assert.match(normalized.content[0].text, /email|邮件/i);
  assert.doesNotMatch(normalized.content[0].text, /^\s*\{/);
}

function testNormalizeMcpToolResultSummarizesExportReviewImages() {
  const normalized = normalizeMcpToolResult("export_review_images", {
    structuredContent: {
      data: {
        products_count: 1,
        image_reviews_count: 2,
        image_links_count: 3,
      },
      artifact: {
        success: true,
        format: "links",
        type: "review_images",
        items: [
          {
            product_name: '16" Meat Saw',
            images: [
              "https://img.example.com/1.jpg",
              "https://img.example.com/2.jpg",
            ],
          },
        ],
      },
    },
  });

  assert.match(normalized.content[0].text, /review image|images/i);
  assert.match(normalized.content[0].text, /16" Meat Saw/);
  assert.match(normalized.content[0].text, /3/);
  assert.match(normalized.content[0].text, /img\.example\.com/);
  assert.doesNotMatch(normalized.content[0].text, /^\s*\{/);
}

function testPluginConfigSchemaRequiresEndpoint() {
  assert.deepEqual(plugin.configSchema.required, ["endpoint"]);
}

function testHighValueToolNamesComeFromSharedContractArtifact() {
  const artifactToolNames = Object.keys(TOOL_CONTRACT_ARTIFACT.tools).sort();
  const contractToolNames = [...CONTRACT_TOOL_NAMES].sort();

  assert.deepEqual(contractToolNames, artifactToolNames);
  assert.ok(!LOCAL_ONLY_TOOL_NAMES.includes("get_stats"));
  assert.ok(!LOCAL_ONLY_TOOL_NAMES.includes("preview_scope"));
}

function testSummarizeProductDetailUsesCanonicalLabel() {
  var result = normalizeMcpToolResult("get_product_detail", {
    structuredContent: {
      name: "Test Product", sku: "TP-001", site: "basspro",
      ownership: "own", price: 29.99, rating: 4.5, review_count: 42,
    },
  });
  var text = result.content[0].text;
  assert.ok(text.includes("站点展示评论总数"), "must use canonical label, got: " + text);
  assert.ok(!text.includes("**评论数**"), "must not use generic 评论数 label");
}

function testSummarizeReviewListRespectsDisplayBudgetOf3() {
  var items = [];
  for (var i = 0; i < 10; i++) {
    items.push({ product_name: "Product " + i, rating: 3, author: "Author " + i });
  }
  var result = normalizeMcpToolResult("query_reviews", {
    structuredContent: { items: items, total: 10 },
  });
  var text = result.content[0].text;
  var sampleMatches = text.match(/^\d+\.\s/gm) || [];
  assert.ok(sampleMatches.length <= 3, "review samples must be <= 3, got " + sampleMatches.length);
}

testExtractSpeakerContextFromMessageEvent();
testBuildSpeakerPromptAdditionsForLeo();
testBuildSpeakerPromptAdditionsForOtherSpeaker();
testExtractToolProvenanceFromHookEvent();
testToolProvenanceSingleToolGrounded();
testToolProvenanceMultiToolAndSqlGrounded();
testToolProvenanceFallsBackToPartialWhenCompletionMissing();
testToolProvenanceForbidsClaimingSqlWhenOnlyAttempted();
testToolProvenanceNoToolsStaysGroundedToNoTools();
testNormalizeMcpToolResultUsesStructuredStatsSummary();
testNormalizeMcpToolResultFailsClearlyWhenCanonicalStatsFieldsAreMissing();
testNormalizeMcpToolResultParsesJsonTextForProductLists();
testNormalizeMcpToolResultSummarizesPreviewScope();
testNormalizeMcpToolResultSummarizesSendFilteredReport();
testNormalizeMcpToolResultSummarizesExportReviewImages();
testPluginConfigSchemaRequiresEndpoint();
testHighValueToolNamesComeFromSharedContractArtifact();
testSummarizeProductDetailUsesCanonicalLabel();
testSummarizeReviewListRespectsDisplayBudgetOf3();

console.log("plugin tests passed");
