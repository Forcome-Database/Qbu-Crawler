# D009 — OpenClaw Routing / Output / Analysis Layering

## 背景

OpenClaw 在高频数据查询场景中出现了两类问题：

1. 流程性回答和分析性回答混在同一套提示词里，导致规则互相竞争
2. 输出模板不完整，尤其缺少“产品列表 / 搜索结果”这一类高频模板

表现上会出现：

- 前半段像结构化总结
- 后半段又夹杂原始工具结果碎片
- 分析回答容易被流程性约束打断

## 目标

按职责重新分层：

- `AGENTS.md`
  - 只放硬路由、禁止事项、状态解释、默认查询路径
- `TOOLS.md`
  - 只放输出契约、展示预算、标准模板
- `skills/qbu-product-data/SKILL.md`
  - 从“SQL 模板清单”升级为“分析 playbook”
- `skills/daily-scrape-report/SKILL.md`
  - 保持 daily 解释 sidecar 的窄职责
- `skills/csv-management/SKILL.md`
  - 保持 CSV 维护 SOP 的刚性和确定性

## 本次调整

### 1. 收紧 AGENTS

- 增加高频查询默认路由：
  - “库里有哪些产品 / 最近抓了什么”
  - “看整体概览”
  - “看差评”
  - “看 daily 是否正常”
- 明确多工具结果必须合并成一条最终回复
- 明确分析 skill 是优先路径，但不是唯一允许路径

### 2. 强化 TOOLS

- 增加“产品列表 / 搜索结果”模板
- 增加“数据概览 + 样本产品”模板
- 增加“workflow 状态”和“通知异常”模板
- 增加默认展示预算和“何时摘要、何时展开”的规则

### 3. 升级 qbu-product-data

- 引入 5 类问题抽象：
  - 概览
  - 对比
  - 趋势
  - 异常
  - 根因 / 改进建议
- 强调先判断问题类型，再选最小必要证据
- 增加证据不足时的保守表达规范
- 保留自由查询 fallback，避免过拟合成固定意图列表

### 4. 保持 daily-report 和 csv-management 的窄职责

- `daily-scrape-report`
  - 只解释 deterministic workflow 的结果
  - 不抢深度分析主导权
- `csv-management`
  - 继续保持“确认 -> 判断 -> 写入/更新 -> 回执”的 SOP
  - 明确不得把 CSV 维护结果伪装成已开始抓取

## 结果预期

- 流程性问题更稳定
- 分析性问题保留泛化能力
- 输出格式更统一、更可读
- 规则不再集中堆在同一个文件里
