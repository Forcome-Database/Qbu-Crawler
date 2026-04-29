# D021 meatyourmaker reviews 折叠容器 max-height:0 卡死 BV 加载

- 日期：2026-04-29
- 范围：`qbu_crawler/scrapers/meatyourmaker.py`、对应回归测试

## 现象（生产 2026-04-29，跨两轮）

### 第 12 轮（v0.4.16）

- run #1 的 `scrape_quality.low_coverage_product`：
  sku=1193465（mym `.5 HP Dual Grind Grinder (#8)`）
  `extracted=0 saved=0 stop_reason=no_shadow_root pages_seen=0 site_total=92`
- 同任务的另一个 mym 产品 1159178 成功提取 109 条；basspro / waltons 三个全部成功。

### 第 13 轮（v0.4.17，第一版修复）

第一版猜测是冷启动 BV 加载慢，把 `_wait_for_shadow_root` 超时从 10s → 30s 并加诊断
日志。结果生产仍报 `no_shadow_root`，但拿到了关键诊断：

```
[mym] _wait_for_shadow_root timeout after 30s; diag={
  "host":true,"shadow":true,"sections":0,
  "has_a_next":false,"has_bv_rid":false,
  "parent_h":95,"rect_top":299,"visible":true,
  "inner_len":771
}
```

inner_len=771 + sections=0 说明 BV widget 已经初始化 shadow root（注入了 style 和
container），但**完全没渲染任何 review section**——超时跟 BV 速度无关。

## 真实根因（浏览器实地复现）

页面 DOM 与 CSS 关系：

```html
<div class="c-toggler c-product__module ... js-pdp-reviews">  <!-- 外层 -->
  <div class="c-toggler__element">Reviews</div>                <!-- 标题 -->
  <div class="c-toggler__content">                             <!-- 折叠容器 -->
    <div data-bv-show="reviews">…</div>                        <!-- BV host -->
  </div>
</div>
```

`.c-toggler__content` 的基线 CSS 是 `max-height: 0; overflow: hidden`。即使外层
`.c-toggler` 加上 `c-toggler--expanded` 类，对应站点 CSS 在冷启动会话下也不一定及时
把 max-height 解开。结果：

1. BV host 自身有 7485px 高度，但被父容器剪到 0 → 在视口内"不可见"
2. BV 的 IntersectionObserver 永远收不到 visible，于是不 fetch reviews
3. shadow root 只注入了 style + container 占位，永远没有 section

更糟的是：旧 `_click_reviews_tab` 用的是 `el.click()`，而 click 是 *toggle*，section
起始就有 `c-toggler--expanded` 类（DOM 默认展开）时，盲 click 反而把它 collapse 掉。
这正是第 13 轮 `parent_h=95` 的成因——内容容器被点合上了。

## 修复

`qbu_crawler/scrapers/meatyourmaker.py`：

1. `_click_reviews_tab` 不再依赖 click，直接通过 JS 强制展开：
   - 给外层 `.c-toggler` 加 `c-toggler--expanded` 类（与点击效果一致，幂等）
   - 给内层 `.c-toggler__content` 设 `style.maxHeight='none'; overflow='visible'`
     以**绕过站点 CSS 时序问题**，让 BV host 立刻可见
   - 等到 `content.offsetHeight > 100` 才返回，最多 10s 找 toggler；
     之后再 sleep 1s 让 React 重渲染稳定
2. `_wait_for_shadow_root`：
   - 默认超时 30s（覆盖冷启动 + 慢代理）
   - 轮询期间每 ~3s 重申"强制展开"（重新加类 + 重设 inline style），
     防止 React 后续重渲染抹掉 inline style 把 BV 重新剪到 0 高度
   - 同步重发 `scroll.to_see`，对抗 IntersectionObserver 一次性触发后失效
   - 超时时 log 当前 host / shadow / sections / parent_h / rect_top / visible
     等诊断字段，便于追踪

## 回归测试

`tests/scrapers/test_mym_reviews_readiness.py`：

- `test_wait_for_shadow_root_succeeds_when_widget_loads_after_initial_timeout`：
  BV 在第 25 次 poll（≈12.5s）才就绪，验证 30s 超时能等到；
  顺带断言至少 reaffirm 一次
- `test_wait_for_shadow_root_logs_diagnostic_on_timeout`：超时走诊断分支
- `test_click_reviews_tab_force_expand_succeeds_immediately`：toggler 一次就绪时
  只调用一次强制展开 JS
- `test_click_reviews_tab_force_expand_retries_when_toggler_not_ready`：toggler
  节点慢渲染时持续轮询直到展开成功

## 验证

- `uv run pytest -q`：985 passed, 3 skipped
- 浏览器在真实 URL 上端到端验证修复 JS 序列：
  - `content_h: 7495`（之前 0）
  - `content_max_h: "none"`（之前 "0px"）
  - `sr_section_count: 11`、`sr_a_next: true` —— BV 已正常渲染 review section

## 未处理 / 后续

- `_wait_for_bv_data` 仍是 10s 静默超时（仅影响 rating summary 的 jsonld 是否被读到，
  不影响 review 抓取），暂不动。
- 暂没在 basspro / waltons 上发现同型 max-height:0 折叠问题；如果将来有新站点接入
  发现类似症状，可复用此处的"force-expand"模式。
