# F002 - 批量抓取

## 需求描述

支持多种方式批量抓取产品数据。

## 功能点

### 1. 从文件读取 URL

- 读取文本文件，每行一个 URL
- `#` 开头的行作为注释跳过
- 空行跳过

```bash
uv run python main.py -f urls.txt
```

### 2. 从分类页自动采集

- 自动打开分类列表页（`/l/xxx` 格式）
- 从产品卡片中提取所有产品链接
- 支持翻页采集
- 可限制最大采集页数
- 采集完成后自动逐个抓取产品详情

```bash
uv run python main.py -c https://www.basspro.com/l/spinning-combos
uv run python main.py -c https://www.basspro.com/l/spinning-combos 3  # 只采集前3页
```

### 3. 命令行直接传入多个 URL

```bash
uv run python main.py URL1 URL2 URL3
```

## 分类页结构

- 产品卡片 class 含 `ItemDetails`
- 产品链接格式：`/shop/en/{product-slug}`
- 分页导航：`nav.styles_pagerContainer__ULou2`
- 下一页箭头：`.iconPagerArrowRight`
- 分页参数：`?page=N&firstResult=(N-1)*pageSize`
- 每页条数可选：36 / 72 / 108
