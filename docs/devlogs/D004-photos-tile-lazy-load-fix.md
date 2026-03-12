# D004 - 修复 .photos-tile 评论图片懒加载丢失

日期：2026-03-11

## 背景

用户反馈 Bass Pro 产品页评论中有照片的评论未被完整采集。以 `bubba-pro-series-smart-fish-scale-cull-kit` 为例，页面有 2 条评论（Knak、Bovee）的用户照片未被采集到。

## 问题分析

### BV 评论图片的两种渲染位置

通过 Chrome 浏览器实际调试 Shadow DOM 发现，BV 评论图片有两种不同的渲染结构：

| 类型 | 位置 | 特征 | 懒加载行为 |
|------|------|------|-----------|
| 归属徽标 | `[data-bv-v="contentSummary"]` 内 | URL 含 `attributionlogo`，尺寸极小（138×65px） | 随 section 渲染即加载 |
| 用户照片 | `.photos-tile` 容器 | URL 含 `photo:basspro-ca`，尺寸正常（600×800px） | **需要 section 在视口内停留才触发** |

### 根因

`_scroll_all_reviews()` 使用 `BATCH_SIZE=20` 批量滚动，当评论总数 < 20 时：

```python
for batch_end in range(BATCH_SIZE - 1, total, BATCH_SIZE):
    idx = min(batch_end, total - 1)  # total=10 → idx=9，直接跳到末尾
```

循环只执行一次，直接 `scrollIntoView` 到最后一个 section。中间含 `.photos-tile` 的 section（如 idx 6、7）一闪而过，`<IMG>` 标签来不及注入。

提取阶段选择器（`.photos-tile img` 或 `img[src*="photos-us.bazaarvoice.com"]`）因为 `<IMG>` 标签不存在，返回空结果。

### 验证

通过浏览器手动滚动到 section 6、7 并等待 0.5 秒后，`.photos-tile` 内的 `<IMG>` 正常出现：
- Knak: `photos-us.bazaarvoice.com/photo/2/cGhvdG86YmFzc3Byby1jYQ/9a8689aa-...`（photo:basspro-ca）
- Bovee: `photos-us.bazaarvoice.com/photo/2/cGhvdG86YmFzc3Byby1jYQ/3fb63048-...`（photo:basspro-ca）

## 修复方案

在 `_scroll_all_reviews()` 的批量滚动后，增加定向滚动逻辑：

1. 用 JS 查找所有含 `.photos-tile` 但 `img[src*="photos-us.bazaarvoice.com"]` 不存在的 section 索引
2. 逐个 `scrollIntoView({block: 'center'})` + `time.sleep(0.5)` 触发懒加载
3. 最后额外等待 1 秒确保图片完成加载

该方案的优势：
- **精准**：只对需要的 section 做额外滚动，不影响大量评论时的批量滚动效率
- **自适应**：无论评论总数多少，只要有未加载的 `.photos-tile` 就会触发
- **无副作用**：如果所有图片已在批量滚动阶段加载，定向滚动不会执行

## 附带确认

归属徽标过滤逻辑工作正常：
- `apps.bazaarvoice.com` 域名的图片被排除（verifiedPurchaser 徽章）
- URL 含 `YXR0cmlidXRpb25sb2dv`（base64 的 `attributionlogo`）的 `photos-us.bazaarvoice.com` 图片被排除

## 文件变更

- `scrapers/basspro.py` — `_scroll_all_reviews()` 增加定向滚动逻辑
- `docs/rules/basspro.md` — 更新图片懒加载说明
- `CLAUDE.md` — DrissionPage 注意事项新增批量滚动跳过懒加载的经验
