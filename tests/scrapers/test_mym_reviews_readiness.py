"""测试 meatyourmaker 评论提取的就绪等待与 toggler 强制展开逻辑。

回归基准：
1. 生产 2026-04-29 第 12 轮（v0.4.16）SKU 1193465 在冷启动会话下
   `_wait_for_shadow_root` 10s 超时直接判 no_shadow_root、0 评论入库。
2. 生产 2026-04-29 第 13 轮（v0.4.17 修复版）虽然超时拉到 30s 仍报
   `parent_h=95、inner_len=771、sections=0` —— 浏览器实地验证后发现：
   - SFCC `c-toggler__content { max-height: 0; overflow: hidden }` 把 BV widget
     剪到 0 高度；BV IntersectionObserver 收不到 visible，永远不 fetch reviews。
   - 单纯 `el.click()` 是 *toggle*；section 起始可能已带 `c-toggler--expanded`，
     盲 click 反而把它 collapse 掉；而即便加上 `c-toggler--expanded` 类，对应
     CSS 在冷启动会话下也未必把 max-height 改成 none。

修复后必须：
1) `_click_reviews_tab` 不依赖 click，直接 JS 设 `c-toggler--expanded` 类 +
   `style.maxHeight='none'` 强制展开，content offsetH > 100 才返回；
2) `_wait_for_shadow_root` timeout=30s，轮询期间每 ~3s 重申"强制展开"以对抗
   React 重渲染抹掉 inline style；超时时打诊断日志。
"""

import json

from qbu_crawler.scrapers.meatyourmaker import MeatYourMakerScraper


class FakeShadowTab:
    """模拟 _wait_for_shadow_root 轮询用的 tab。

    poll_count_until_populated: 第 N 次 populated 检查时 shadow root 才有 section；
        填 None 表示永远不就绪（仅用于触发超时路径）。
    每次 run_js 接收 JS 字符串，根据脚本内容粗匹配返回不同结果。
    """

    def __init__(self, poll_count_until_populated):
        self.poll_count_until_populated = poll_count_until_populated
        self.populated_calls = 0
        self.diag_calls = 0
        self.reaffirm_calls = 0

    def run_js(self, script):
        # 优先匹配诊断脚本（含 "host" 字段的 JSON.stringify）
        if "JSON.stringify({" in script and "host:" in script:
            self.diag_calls += 1
            return json.dumps({"host": True, "shadow": True, "sections": 0})
        # populated check：含 "querySelector('section')" 且直接 `return 1`
        if "querySelector('section')" in script and "return 1" in script:
            self.populated_calls += 1
            if (self.poll_count_until_populated is not None
                    and self.populated_calls >= self.poll_count_until_populated):
                return 1
            return 0
        # reaffirm_expand：含 "c-toggler--expanded" 字面量
        if "c-toggler--expanded" in script:
            self.reaffirm_calls += 1
            return 1
        return None

    def ele(self, *_args, **_kwargs):
        # scroll_into_view 容错；返回带 scroll.to_see 的对象
        class _Host:
            class _Scroll:
                def to_see(self, **__):
                    return None

            scroll = _Scroll()

        return _Host()


def _fresh_scraper(monkeypatch):
    scraper = MeatYourMakerScraper.__new__(MeatYourMakerScraper)
    monkeypatch.setattr(
        "qbu_crawler.scrapers.meatyourmaker.time.sleep",
        lambda *_a, **_kw: None,
    )
    return scraper


def test_wait_for_shadow_root_succeeds_when_widget_loads_after_initial_timeout(monkeypatch):
    """生产冷启动场景：BV widget 在第 25 次 poll（≈12.5s）才注入 sections，
    旧 10s 超时会判 no_shadow_root，新 30s 超时能成功返回 True。"""
    scraper = _fresh_scraper(monkeypatch)
    tab = FakeShadowTab(poll_count_until_populated=25)

    assert scraper._wait_for_shadow_root(tab, timeout=30) is True
    assert tab.populated_calls == 25
    # 成功路径不应该走诊断分支
    assert tab.diag_calls == 0
    # 至少应该 reaffirm 一次（进入 poll 循环前就调一次）
    assert tab.reaffirm_calls >= 1


def test_wait_for_shadow_root_logs_diagnostic_on_timeout(monkeypatch):
    """超时路径必须打诊断日志，便于追踪故障是 host 缺失还是 shadow 未注入内容。"""
    scraper = _fresh_scraper(monkeypatch)
    tab = FakeShadowTab(poll_count_until_populated=None)  # 永远不就绪

    assert scraper._wait_for_shadow_root(tab, timeout=2) is False
    assert tab.diag_calls == 1


class FakeForceExpandTab:
    """模拟 _click_reviews_tab 强制展开逻辑用的 tab。

    expand_after_n_calls: 第 N 次状态脚本被调用时返回 expanded=True
    （模拟 toggler 还没渲染好的状态）。
    """

    def __init__(self, expand_after_n_calls: int):
        self.expand_after_n_calls = expand_after_n_calls
        self.expand_calls = 0

    def run_js(self, script):
        # 强制展开脚本：返回 found/expanded/content_h
        if "c-toggler--expanded" in script and "JSON.stringify" in script:
            self.expand_calls += 1
            if self.expand_calls >= self.expand_after_n_calls:
                return json.dumps({
                    "found": True, "expanded": True, "content_h": 7500
                })
            # 未就绪：toggler 还没找到
            return json.dumps({"found": False})
        return None


def test_click_reviews_tab_force_expand_succeeds_immediately(monkeypatch):
    """初始页面已就绪：第一次调用 JS 就能加类 + 设 max-height，content_h 立刻 > 100。"""
    scraper = _fresh_scraper(monkeypatch)
    tab = FakeForceExpandTab(expand_after_n_calls=1)

    scraper._click_reviews_tab(tab)

    # 第一次就成功；后续不再重复调用
    assert tab.expand_calls == 1


def test_click_reviews_tab_force_expand_retries_when_toggler_not_ready(monkeypatch):
    """toggler 节点还没渲染：前几次 JS 报 found=False，需要持续轮询直到 toggler 出现并展开。"""
    scraper = _fresh_scraper(monkeypatch)
    tab = FakeForceExpandTab(expand_after_n_calls=4)

    scraper._click_reviews_tab(tab)

    # 至少经过 4 次轮询才成功
    assert tab.expand_calls >= 4
