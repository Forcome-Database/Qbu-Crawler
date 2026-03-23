# Qbu-Crawler

多站点产品数据爬虫 — 基于 DrissionPage，抓取产品详情（名称、SKU、价格、库存、评分、评论）并存储到 SQLite。

## 支持站点

| 站点 | 反爬系统 | 代理自动降级 |
|------|----------|-------------|
| Bass Pro Shops | Akamai | 支持 |
| Walton's | Cloudflare | 支持 |
| Meat Your Maker | 弱 | 支持 |

## 安装

```bash
# uvx 直接运行（推荐，无需安装）
uvx qbu-crawler

# 或 pip 安装
pip install qbu-crawler
```

## 使用

```bash
# 抓取单个产品
qbu-crawler <product-url>

# 从文件批量抓取
qbu-crawler -f urls.txt

# 从分类页采集并抓取
qbu-crawler -c <category-url>

# 多站点分类页并行采集
qbu-crawler -c <basspro-category> -c <waltons-category>

# 启动 HTTP API + MCP 服务
qbu-crawler serve [--host 0.0.0.0] [--port 9000]
```

## 配置

在当前目录或 `~/.qbu-crawler/` 下创建 `.env` 文件，参考 `.env.example`。

### 代理池配置

在数据中心/服务器部署时，Akamai 等反爬系统会封锁数据中心 IP。通过配置代理池 API，爬虫可在遇到 Access Denied 时自动获取住宅代理 IP 重试。

```env
# 代理池 API 地址（返回 ip:port 格式，留空则不使用）
PROXY_API_URL=https://white.1024proxy.com/white/api?region=US&num=1&time=10&format=1&type=txt
PROXY_MAX_RETRIES=3
```

**工作原理：**

1. 首次请求直连目标站点
2. 检测到封锁（Akamai "Access Denied" / Cloudflare challenge）→ 从代理 API 获取 IP
3. 重启浏览器（`--proxy-server`）→ 带代理重试
4. 仍被封锁 → 轮换新 IP → 重启 → 重试（最多 `PROXY_MAX_RETRIES` 次）
5. 代理 IP 带 TTL 缓存，有效期内复用，过期或被封时自动刷新

未配置代理时，不影响正常使用；本地有住宅 IP 的环境无需配置。

## 从源码运行

```bash
uv sync
uv run python main.py <product-url>
uv run python main.py serve
```

## 发布

### 一键脚本发布

```bash
python scripts/publish.py <版本类型> [选项]
```

**版本类型（必填）：**

| 参数 | 示例 | 说明 |
|------|------|------|
| `patch` | 0.1.2 → 0.1.3 | 补丁版本 |
| `minor` | 0.1.2 → 0.2.0 | 次版本 |
| `major` | 0.1.2 → 1.0.0 | 主版本 |
| `x.y.z` | 指定版本 | 自定义版本号 |

**选项（可组合）：**

| 选项 | 说明 |
|------|------|
| `--dry-run` | 只构建不发布，不提交 git |
| `--test-pypi` | 发布到 TestPyPI 测试 |
| `--no-git` | 跳过 git commit/tag/push |

脚本自动完成：清理 dist → 更新版本号（`pyproject.toml` + `__init__.py`）→ 构建 → 发布到 PyPI → git commit + tag + push。

### CI 自动发布

推送 `v*` 格式的 git tag 后，GitHub Actions 自动构建并发布到 PyPI（Trusted Publisher，无需 API Token）。

手动脚本会自动推送 tag，因此 `python scripts/publish.py patch` 一条命令即可完成「本地发布 + 触发 CI」全流程。
