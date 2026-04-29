# D025 测试10 P4 采集真相与报告契约

## 背景

测试10生产产物显示日报只覆盖 7 个产品、565 条评论，运维日志里 BassPro `cabelas-heavy-duty-20-lb-meat-mixer` 在产品页 `h1` 等待阶段触发 `KeyError('searchId')`。业务报告本身继续生成，但此前链路没有把计划 URL、成功 URL、失败 URL 作为采集真相持久化，导致漏采只能靠终端日志回溯。

同一轮报告还暴露出报告契约偏移：最终 HTML 可能保留空 snapshot 派生值，LLM 数字校验不认识 contract 中锁定的 evidence count，Excel 竞品启示缺少产品和证据字段，评分 KPI 口径也容易把全样本和自有样本混在一起。

## 根因

- BassPro 产品身份就绪依赖 `tab.wait.ele_displayed('tag:h1')`，该路径会触发 DrissionPage 底层 `DOM.getSearchResults`。当 CDP 返回结构缺少 `searchId` 时，异常直接让单 URL 失败。
- TaskManager 只沉淀任务总体结果，没有 URL 级 `expected/saved/failed` 对账事实；workflow quality 只能从入库 snapshot 反推完整率。
- run log 和运维邮件缺少失败 URL 的阶段、错误类型、错误信息和 diagnostics，用户业务报告与技术追踪的职责边界不够清晰。
- `report_user_contract` 的部分派生字段在真实 snapshot 到达后没有统一刷新，空 LLM copy 也可能覆盖已有确定性行动建议。
- LLM known numbers 只看 KPI 和风险产品，未纳入 contract evidence pack 中已经锁定的证据数和影响产品数。
- `sample_avg_rating` 与 `own_avg_rating` 口径混用，导致用户看到的评分指标不够可解释。

## 修复

- BassPro 产品身份改为轻量 JS 轮询 `h1` / `document.title`，绕开不稳定的元素搜索路径；补充 age gate 多阶段轻量检查和 BV `shadow_empty` 等诊断。
- task result 增加 `expected_urls`、`saved_urls`、`failed_urls` 及计数字段，失败 URL 记录 `url/site/stage/error_type/error_message/diagnostics`。
- 采集质量统计优先使用 expected/saved/failed URL 对账，run log 输出失败 URL 明细，运维邮件发送简要技术摘要，用户业务报告不展示工程诊断。
- contract 刷新保留有效行动建议和 explicit `evidence_count`，用真实 snapshot 更新 bootstrap digest、影响产品数和竞品启示字段。
- LLM 一致性校验纳入 contract evidence counts 和 affected product counts。
- `sample_avg_rating` 使用全样本评论均分，`own_avg_rating` 使用自有产品评论均分，并新增竞品均分。
- Excel 竞品启示只消费 contract item，输出主题、涉及竞品、证据数、证据评论 ID、竞品信号和验证假设。
- 增加测试10最小 replay，锁住业务报告与运维日志隔离。

## 验证

已按计划补充定向测试，覆盖 BassPro readiness、task result URL 级失败、scrape quality、run log、运维邮件、contract、renderer、LLM known numbers、Excel 和测试10 replay。

推荐最终验证命令：

```powershell
uv run --extra dev python -m pytest tests/scrapers/test_basspro_readiness.py tests/server/test_task_manager_failed_urls.py tests/test_scrape_quality.py tests/server/test_run_log.py tests/server/test_internal_ops_alert.py tests/server/test_workflow_ops_alert_wiring.py tests/server/test_report_contract.py tests/server/test_report_contract_renderers.py tests/server/test_report_contract_llm.py tests/test_metric_semantics.py tests/test_v3_excel.py tests/server/test_test10_artifact_replay.py -q
```

受评分 KPI 口径影响的专项验证：

```powershell
uv run --extra dev python -m pytest tests/test_report_analytics.py::test_build_report_analytics_includes_own_avg_rating tests/test_report_analytics.py::test_sample_avg_rating_computed_from_reviews -q
```

BassPro 本地实测必须使用隔离 DB 和 REPORT_DIR，只跑单个 meat mixer URL，不扩大 URL 集合，不高频刷新，不绕过 Akamai 或站点访问控制。
