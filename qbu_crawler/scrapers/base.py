import json
import logging
import os
import subprocess
import sys
import threading
import time
from urllib.parse import urlparse

from DrissionPage import Chromium, ChromiumOptions
from qbu_crawler.config import (
    HEADLESS, PAGE_LOAD_TIMEOUT, NO_IMAGES,
    RETRY_TIMES, RETRY_INTERVAL, REQUEST_DELAY, RESTART_EVERY,
    CHROME_USER_DATA_PATH,
)

logger = logging.getLogger(__name__)


def _has_display() -> bool:
    """检测当前环境是否有可用的显示服务（X11/Wayland/Windows）"""
    if sys.platform == 'win32':
        return True
    return bool(os.environ.get('DISPLAY') or os.environ.get('WAYLAND_DISPLAY'))


def _ensure_virtual_display():
    """Linux 无显示环境时，自动启动 Xvfb 虚拟显示。
    需要安装：apt install xvfb + pip install PyVirtualDisplay
    """
    if sys.platform == 'win32' or _has_display():
        return
    try:
        from pyvirtualdisplay import Display
        display = Display(visible=0, size=(1920, 1080))
        display.start()
        logger.info(f"已启动虚拟显示 (DISPLAY={os.environ.get('DISPLAY')})")
    except ImportError:
        logger.warning(
            "Linux 无显示环境且未安装 PyVirtualDisplay，"
            "请运行: pip install PyVirtualDisplay && apt install xvfb"
        )


def _find_chrome() -> str:
    """查找 Chrome 可执行文件路径"""
    if sys.platform == 'win32':
        for path in [
            os.path.expandvars(r'%ProgramFiles%\Google\Chrome\Application\chrome.exe'),
            os.path.expandvars(r'%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe'),
            os.path.expandvars(r'%LocalAppData%\Google\Chrome\Application\chrome.exe'),
        ]:
            if os.path.isfile(path):
                return path
    else:
        for name in ['google-chrome', 'google-chrome-stable', 'chromium-browser', 'chromium']:
            import shutil
            path = shutil.which(name)
            if path:
                return path
    raise FileNotFoundError("Chrome executable not found")


class BaseScraper:
    # 用户数据模式下 Chrome 使用的固定调试端口
    _USER_DATA_PORT = 19222

    # ── 站点级属性（子类可覆盖）──
    SITE_LOAD_MODE: str = "eager"       # 页面加载模式
    SITE_NEEDS_USER_DATA: bool = False  # 是否需要 Chrome 用户数据模式
    SITE_RESTART_SAFE: bool = True      # 浏览器重启是否安全（不丢关键 cookie）
    _user_data_lock = threading.Lock()

    def __init__(self):
        if HEADLESS and not _has_display():
            _ensure_virtual_display()
        self._use_user_data = bool(CHROME_USER_DATA_PATH) and self.SITE_NEEDS_USER_DATA
        self._proxy = None  # 当前使用的代理 (ip:port)
        self._warmed_up = False
        if self._use_user_data:
            self._proxy = self._get_initial_proxy()
            self.browser = self._launch_with_user_data(proxy=self._proxy)
        else:
            self.browser = self._create_browser()
        self._scrape_count = 0

    def _create_browser(self, proxy: str | None = None) -> Chromium:
        """创建浏览器实例，可选代理"""
        options = self._build_options()
        if proxy:
            options.set_argument(f'--proxy-server=http://{proxy}')
        return Chromium(options)

    def _build_options(self) -> ChromiumOptions:
        options = ChromiumOptions()
        options.auto_port()  # 每个实例使用独立端口，防止并行任务共享浏览器
        if HEADLESS:
            if _has_display():
                options.headless()
            options.set_argument('--window-size=1920,1080')
        else:
            options.set_argument('--start-maximized')
        if NO_IMAGES:
            options.no_imgs(True)
        options.set_load_mode(self.SITE_LOAD_MODE)
        options.set_retry(times=RETRY_TIMES, interval=RETRY_INTERVAL)
        options.set_timeouts(base=10, page_load=PAGE_LOAD_TIMEOUT)
        options.set_argument('--deny-permission-prompts')
        options.set_argument('--disable-blink-features=AutomationControlled')
        return options

    @classmethod
    def _find_pids_on_port(cls, port: int) -> list[str]:
        """按 TCP 端口查所有 LISTENING 的 PID。
        兼容 Windows 11 带 Offload State 列的 netstat 输出：
          "TCP 127.0.0.1:19222 0.0.0.0:0 LISTENING 12345 InHost"
        以 "LISTENING" 关键字定位 PID，而非固定位置偏移。"""
        if sys.platform != 'win32':
            return []
        try:
            result = subprocess.run(
                ['netstat', '-ano', '-p', 'TCP'],
                capture_output=True, text=True, timeout=5,
            )
        except Exception as e:
            logger.warning(f"[启动] netstat 调用失败: {e}")
            return []
        pids = []
        for line in result.stdout.splitlines():
            if 'LISTENING' not in line:
                continue
            parts = line.split()
            if len(parts) < 4:
                continue
            # 本地地址列严格以 ":{port}" 结尾（防 ":192220" 之类误命中）
            local_addr = parts[1]
            if not local_addr.endswith(f':{port}'):
                continue
            try:
                idx = parts.index('LISTENING')
                pid = parts[idx + 1]
                if pid.isdigit() and pid not in pids:
                    pids.append(pid)
            except (ValueError, IndexError):
                continue
        return pids

    @classmethod
    def _find_chrome_pids_by_cmdline(cls, port: int) -> list[int]:
        """按 cmdline 精确识别用户数据 Chrome 主进程（同时含 port + user-data-dir）。
        用于定位 CDP 已关但主进程仍活的"后台保持运行"僵尸。"""
        pids = []
        try:
            import psutil
        except ImportError:
            return pids
        marker_port = f'--remote-debugging-port={port}'
        marker_userdata = f'--user-data-dir={CHROME_USER_DATA_PATH}' if CHROME_USER_DATA_PATH else None
        for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
            try:
                name = (proc.info.get('name') or '').lower()
                if name not in ('chrome.exe', 'chrome'):
                    continue
                cmdline = proc.info.get('cmdline') or []
                joined = ' '.join(cmdline)
                if marker_port not in joined:
                    continue
                if marker_userdata and marker_userdata not in joined:
                    continue
                pids.append(proc.info['pid'])
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        return pids

    @classmethod
    def _kill_all_chrome_with_userdata(cls) -> int:
        """按 user-data-dir 核爆所有 chrome 进程（含 renderer/helper 子进程）。
        Chrome 主进程 kill 后，renderer/GPU/utility 子进程可能仍活着，它们 cmdline
        里有 --user-data-dir=... 但没有 --remote-debugging-port=...，
        _find_chrome_pids_by_cmdline 漏掉→这些子进程仍握 profile 锁，
        新 Popen 的 Chrome IPC 给"看不见的持有者"后自退→死循环。"""
        if not CHROME_USER_DATA_PATH:
            return 0
        try:
            import psutil
        except ImportError:
            return 0
        marker = f'--user-data-dir={CHROME_USER_DATA_PATH}'
        killed = 0
        for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
            try:
                name = (proc.info.get('name') or '').lower()
                if name not in ('chrome.exe', 'chrome'):
                    continue
                cmdline = ' '.join(proc.info.get('cmdline') or [])
                if marker not in cmdline:
                    continue
                try:
                    psutil.Process(proc.info['pid']).kill()
                    killed += 1
                except Exception:
                    pass
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        if killed:
            logger.warning(f"[启动] user-data-dir nuclear kill {killed} 个 chrome 进程（含子进程）")
        return killed

    @classmethod
    def _kill_user_data_chrome(cls, port: int):
        """关闭占用指定调试端口的 Chrome 进程。
        三层策略：
          1. CDP force=True 路径（走 SystemInfo.getProcessInfo + psutil.kill）
          2. 按 cmdline 识别 chrome.exe 并 psutil.kill（补"后台保持运行"漏网）
          3. netstat 按端口 LISTENING 兜底（理论上 1/2 都失败才用得到）
        """
        # 1. CDP force=True，让 DrissionPage 自己通过 CDP SystemInfo 拿 PID 列表杀
        try:
            browser = Chromium(port)
            browser.quit(force=True, timeout=5)
        except Exception:
            try:
                browser = Chromium(port)
                browser.quit()
            except Exception:
                pass

        # 2. psutil 按 cmdline 找。处理"CDP 已关但 Chrome 进程因后台机制仍活着"的场景
        try:
            import psutil
            for attempt in range(3):
                pids = cls._find_chrome_pids_by_cmdline(port)
                if not pids:
                    break
                for pid in pids:
                    logger.warning(f"[启动] 按 cmdline 命中 Chrome PID {pid}，kill (attempt {attempt + 1})")
                    try:
                        p = psutil.Process(pid)
                        # 先 kill 子进程树，再 kill 主进程
                        for child in p.children(recursive=True):
                            try: child.kill()
                            except Exception: pass
                        p.kill()
                    except Exception as e:
                        logger.warning(f"[启动] psutil kill PID {pid} 失败: {e}")
                time.sleep(0.5)
        except ImportError:
            pass

        if sys.platform != 'win32':
            return

        # 3. netstat 按端口 LISTENING 兜底（psutil 失效或 cmdline 无法匹配时）
        for attempt in range(3):
            pids = cls._find_pids_on_port(port)
            if not pids:
                return
            for pid in pids:
                logger.warning(f"[启动] 端口 {port} 被 PID {pid} 占用，taskkill /F /T (attempt {attempt + 1})")
                try:
                    subprocess.run(
                        ['taskkill', '/F', '/T', '/PID', pid],
                        capture_output=True, timeout=5,
                    )
                except Exception as e:
                    logger.warning(f"[启动] taskkill PID {pid} 失败: {e}")
            time.sleep(0.5)
        still = cls._find_pids_on_port(port)
        if still:
            logger.error(f"[启动] 强杀后端口 {port} 仍被 PID {still} 占用")

        # 4. 按 user-data-dir 核爆所有 chrome 子进程（renderer/helper 常没有 port marker）
        cls._kill_all_chrome_with_userdata()

    @staticmethod
    def _clean_singleton_locks():
        """清理用户数据目录下的 Chrome 单实例锁文件。
        Chrome 异常退出后，SingletonLock/SingletonCookie/SingletonSocket 可能残留，
        导致新 Chrome 进程把命令 IPC 给"锁持有者"后立刻退出（即使持有者已死）。
        """
        if not CHROME_USER_DATA_PATH:
            return
        for name in ('SingletonLock', 'SingletonCookie', 'SingletonSocket'):
            path = os.path.join(CHROME_USER_DATA_PATH, name)
            try:
                if os.path.lexists(path):
                    os.remove(path)
                    logger.info(f"[启动] 清理残留 {name}")
            except Exception as e:
                logger.warning(f"[启动] 清理 {name} 失败: {e}")

    @classmethod
    def _snapshot_chrome_env(cls, tag: str):
        """启动前/清理前的环境快照诊断日志。
        打印：
          - 端口 19222 的 LISTENING PID
          - 所有 chrome.exe 进程的 pid + cmdline（按是否含 user-data-dir 分组）
        生产复现时直接看日志就能判断"谁占着 profile"，不用登服务器跑 tasklist。

        cmdline 太长时截断到 300 字符 + 关键 marker 是否出现。"""
        port = cls._USER_DATA_PORT
        marker_userdata = f'--user-data-dir={CHROME_USER_DATA_PATH}' if CHROME_USER_DATA_PATH else None
        marker_port = f'--remote-debugging-port={port}'
        logger.info(f"[诊断/{tag}] ── chrome 环境快照 ──")
        try:
            listening = cls._find_pids_on_port(port)
            logger.info(f"[诊断/{tag}] 端口 {port} LISTENING PID: {listening or '（无）'}")
        except Exception as e:
            logger.warning(f"[诊断/{tag}] netstat 失败: {e}")
        try:
            import psutil
        except ImportError:
            logger.info(f"[诊断/{tag}] psutil 不可用，跳过 chrome.exe 枚举")
            return
        ours = []   # 含我们的 user-data-dir 的 chrome 进程
        others = []  # 其他 chrome.exe（用户真 profile 等）
        for proc in psutil.process_iter(['pid', 'name', 'cmdline', 'create_time']):
            try:
                name = (proc.info.get('name') or '').lower()
                if name not in ('chrome.exe', 'chrome'):
                    continue
                cmdline = ' '.join(proc.info.get('cmdline') or [])
                entry = {
                    'pid': proc.info['pid'],
                    'cmdline': cmdline[:300] + ('…' if len(cmdline) > 300 else ''),
                    'has_port': marker_port in cmdline,
                    'has_userdata': bool(marker_userdata and marker_userdata in cmdline),
                }
                if entry['has_userdata']:
                    ours.append(entry)
                else:
                    others.append(entry)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        logger.info(
            f"[诊断/{tag}] 持 user-data-dir={CHROME_USER_DATA_PATH} 的 chrome 进程：{len(ours)} 个"
        )
        for e in ours:
            logger.info(
                f"[诊断/{tag}]   PID {e['pid']} port_marker={e['has_port']} cmdline={e['cmdline']}"
            )
        logger.info(f"[诊断/{tag}] 其他 chrome.exe（与 QBU profile 无关）：{len(others)} 个")
        # "其他" 通常是用户自己的 Chrome，pid 打印即可，cmdline 不打（隐私 + 噪音）
        if others:
            logger.info(f"[诊断/{tag}]   PIDs: {[e['pid'] for e in others]}")

    @classmethod
    def _launch_with_user_data(cls, proxy: str | None = None) -> Chromium:
        """使用 Chrome 用户数据启动浏览器，可选代理。
        Chrome 支持 --user-data-dir + --proxy-server 同时使用，
        代理通过 HTTP CONNECT 隧道，JA3 指纹不变。

        用 _user_data_lock 串行化启动流程，防多个用户数据 scraper 并发 init
        时互相踩脚（第一个 Popen 刚起来就被第二个 kill 掉）。"""
        with cls._user_data_lock:
            return cls._launch_with_user_data_locked(proxy=proxy)

    @classmethod
    def _launch_with_user_data_locked(cls, proxy: str | None = None) -> Chromium:
        port = cls._USER_DATA_PORT

        # 入口快照：启动前环境里"谁已经在用我们的 profile"一目了然
        cls._snapshot_chrome_env("启动前")

        if proxy:
            # 代理是启动参数，切换代理必须重启 Chrome
            cls._kill_user_data_chrome(port)
        else:
            # 无代理时尝试连接已运行的 Chrome。
            # ⚠ 关键：DrissionPage 的 Chromium(port) 在端口空闲时会自动拉一个白板 Chrome
            # （走 DrissionPage 默认参数，完全忽略我们的 --user-data-dir），导致每次启动
            # 都多一次无意义的白板 Chrome + probe 失败 fallthrough。
            # 因此先 netstat 确认有 LISTENING 再进复用分支；空端口直接 fall through
            # 到下面的 subprocess 启动分支，用我们自己的 user-data-dir 参数拉 Chrome。
            if cls._find_pids_on_port(port):
                try:
                    browser = Chromium(port)
                    cls._cleanup_tabs(browser)
                    if not cls._probe_browser_alive(browser):
                        raise RuntimeError("复用的 Chrome 健康探测失败（僵尸进程）")
                    return browser
                except Exception as e:
                    logger.warning(f"[启动] 端口 {port} 复用失败，将重启 Chrome: {e}")
                    cls._kill_user_data_chrome(port)

        # Popen 前快照：kill/清锁后还剩哪些 chrome.exe，是否真的清干净了
        cls._snapshot_chrome_env("Popen前")

        cls._clean_singleton_locks()
        chrome_path = _find_chrome()
        args = [
            chrome_path,
            f'--remote-debugging-port={port}',
            f'--user-data-dir={CHROME_USER_DATA_PATH}',
            '--profile-directory=Default',
            '--disable-blink-features=AutomationControlled',
            '--deny-permission-prompts',
            '--no-first-run',
            '--no-default-browser-check',
            'about:blank',
        ]
        if proxy:
            args.append(f'--proxy-server=http://{proxy}')
        if HEADLESS and _has_display():
            args.append('--headless=new')
        args.append('--disable-session-crashed-bubble')
        subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        last_err = None
        dead_streak = 0
        for attempt in range(40):  # 40s 总窗口，生产上 Chrome 冷启动（大用户数据+并发）可能超 20s
            time.sleep(1)
            # 严格先等我们 Popen 的 Chrome 起来再连，防 DrissionPage 在端口空时自作主张
            # 拉一个白板 Chrome 覆盖我们的进程。
            if not cls._find_pids_on_port(port):
                # 进一步诊断：我们刚 Popen 的 Chrome 进程是否还活着？
                chrome_alive = bool(cls._find_chrome_pids_by_cmdline(port))
                if chrome_alive:
                    last_err = f"Chrome 进程存活但尚未 LISTENING (attempt {attempt + 1})"
                    dead_streak = 0
                else:
                    dead_streak += 1
                    last_err = f"Popen 的 Chrome 已退出（SingletonLock IPC?）(attempt {attempt + 1})"
                    # Chrome 连续 3 秒不存在 → Popen 的 Chrome 被 SingletonLock IPC 给"某个看不见的持有者"后自己退出了
                    # 重清 Lock 重新 Popen 一次，还失败就让外面抛
                    if dead_streak >= 3:
                        logger.warning(f"[启动] {last_err}，重清 SingletonLock 重新 Popen")
                        # 关键诊断点：Popen 的 Chrome 立刻退了，此刻快照能直接看到
                        # 到底是哪个 chrome.exe 抢走了 profile 的 IPC
                        cls._snapshot_chrome_env("Popen自退")
                        cls._kill_user_data_chrome(port)
                        cls._clean_singleton_locks()
                        subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                        dead_streak = 0
                continue
            try:
                browser = Chromium(port)
                cls._cleanup_tabs(browser)
                # CDP 端口有时先于 page target 就绪，此时 latest_tab 会 IndexError。
                # 探测未通过就继续等，别返回一个半死浏览器。
                if not cls._probe_browser_alive(browser):
                    last_err = "page target 未就绪"
                    continue
                return browser
            except Exception as e:
                last_err = repr(e)
                continue
        raise RuntimeError(
            f"Chrome with user data failed to start on port {port}: {last_err}"
        )

    @staticmethod
    def _cleanup_tabs(browser):
        """清理多余标签：先开一个 fresh about:blank，再关掉所有旧 tab。

        ⚠ 不能简单保留 tabs[-1] 然后关 tabs[:-1]：DrissionPage 的 browser.latest_tab
        返回 tab_ids[0]（CDP Target.getTargets 里排最前的 target），而 get_tabs()
        的 tabs[0] 正好就是 latest_tab；tabs[:-1] 会把它关掉，后续 _probe_browser_alive
        读 latest_tab.url 会撞到 "connection to the page has been disconnected"。

        做法：先 new_tab 建新页，它自动成为最新 target → latest_tab 指向它；
        然后关掉所有原 tab，探测稳定、状态可预期。
        """
        try:
            tabs = browser.get_tabs()
        except Exception as e:
            logger.warning(f"[清理] get_tabs 失败: {e}")
            return
        if len(tabs) <= 1:
            return
        try:
            fresh = browser.new_tab('about:blank')
        except Exception as e:
            logger.warning(f"[清理] new_tab 失败，跳过清理: {e}")
            return
        fresh_id = getattr(fresh, 'tab_id', None)
        closed = 0
        for tab in tabs:
            try:
                if fresh_id and getattr(tab, 'tab_id', None) == fresh_id:
                    continue
                tab.close()
                closed += 1
            except Exception:
                pass
        logger.info(f"[清理] 关闭 {closed} 个旧标签（共 {len(tabs)} 个），保留新建 about:blank")

    @staticmethod
    def _probe_browser_alive(browser) -> bool:
        """健康探测：确认 Chrome CDP 既能握手又能真正执行操作。
        僵尸场景：端口残留、Chromium(port) 成功，但 new_tab/latest_tab 立刻 refused。
        探测逻辑：若无 page target 就开一个 about:blank；然后读 latest_tab.url。
        任一步失败 → 返回 False，上层重启 Chrome。"""
        try:
            if browser.tabs_count == 0:
                browser.new_tab('about:blank')
            # latest_tab + .url 会走一次 CDP Target.getTargets + Runtime
            _ = browser.latest_tab.url
            return True
        except Exception as e:
            logger.warning(f"[启动] 浏览器健康探测失败: {e}")
            return False

    def _warm_up(self):
        """访问站点首页完成反爬 challenge（如 Akamai _abck cookie）。
        子类可覆盖提供站点特定的预热逻辑。默认不做任何事。"""
        pass

    def _get_initial_proxy(self) -> str | None:
        """初始化时获取代理 IP（如果站点需要代理）"""
        from qbu_crawler.proxy import get_proxy_pool
        pool = get_proxy_pool()
        if pool:
            proxy = pool.get()
            if proxy:
                logger.info(f"[初始化] 用户数据模式 + 代理: {proxy}")
                return proxy
        return None

    def _maybe_restart_browser(self):
        """定期重启浏览器，防止长时间运行内存泄漏"""
        if not self.SITE_RESTART_SAFE:
            return  # 站点声明重启不安全（如 Akamai _abck cookie）
        if RESTART_EVERY and self._scrape_count > 0 and self._scrape_count % RESTART_EVERY == 0:
            print(f"  [优化] 已抓取 {self._scrape_count} 个产品，重启浏览器释放内存")
            try:
                self.browser.quit()
            except Exception:
                pass
            self.browser = self._create_browser(proxy=self._proxy)

    @staticmethod
    def _check_url_match(tab, expected_url: str):
        """检查导航后的实际 URL 是否匹配预期，防止并行任务导致数据错位。
        允许站点内分类路径重定向（如 /process/product → /nwtf/product），
        只要域名和最终产品标识（路径末段）一致即可。"""
        actual_url = tab.url
        expected_parsed = urlparse(expected_url)
        actual_parsed = urlparse(actual_url)
        # 域名必须一致
        if expected_parsed.netloc != actual_parsed.netloc:
            logger.warning(f"URL 域名不匹配！预期: {expected_url} → 实际: {actual_url}")
            raise RuntimeError(
                f"页面域名不匹配（可能被重定向到其他站点）: "
                f"预期 {expected_url}, 实际 {actual_url}"
            )
        # 最终路径段（产品标识）必须一致，允许中间分类路径变化
        expected_slug = expected_parsed.path.rstrip("/").rsplit("/", 1)[-1]
        actual_slug = actual_parsed.path.rstrip("/").rsplit("/", 1)[-1]
        if expected_slug != actual_slug:
            logger.warning(f"URL 产品标识不匹配！预期: {expected_url} → 实际: {actual_url}")
            raise RuntimeError(
                f"页面产品标识不匹配（可能被重定向或并行任务干扰）: "
                f"预期 {expected_url}, 实际 {actual_url}"
            )
        if expected_parsed.path != actual_parsed.path:
            logger.info(f"URL 路径重定向: {expected_parsed.path} → {actual_parsed.path}（产品标识一致，继续）")

    @staticmethod
    def _is_cloudflare(tab) -> bool:
        """检测当前页面是否是 Cloudflare challenge/Turnstile 页面"""
        try:
            title = tab.title or ""
            html_head = (tab.html or "")[:5000].lower()
            # 标题匹配（多语言）
            if ("just a moment" in title.lower() or "请稍候" in title) \
                    and "cloudflare" in html_head:
                return True
            # Turnstile 页面结构特征（不依赖标题）
            if "challenges.cloudflare.com" in html_head:
                return True
            if "cf-turnstile" in html_head or "cf-chl-widget" in html_head:
                return True
            return False
        except Exception:
            return False

    @staticmethod
    def _is_blocked(tab) -> bool:
        """检测页面是否被反爬系统封锁（Akamai / Cloudflare / Chrome 错误）"""
        try:
            title = tab.title or ""
            url = tab.url or ""
            html_head = (tab.html or "")[:5000].lower()
            # Chrome 内部错误页面（代理连接失败、DNS 失败、网络不可达等）
            if url.startswith("chrome-error://"):
                return True
            if "id=\"main-frame-error\"" in html_head or "neterror" in html_head:
                return True
            # Akamai: "Access Denied" + errors.edgesuite.net
            if "Access Denied" in title:
                return True
            if "errors.edgesuite.net" in url:
                return True
            # Cloudflare（所有形态）
            if ("just a moment" in title.lower() or "请稍候" in title):
                return True
            if "challenges.cloudflare.com" in html_head:
                return True
            if "cf-turnstile" in html_head or "cf-chl-widget" in html_head:
                return True
            return False
        except Exception:
            return False

    def _wait_and_solve_cloudflare(self, tab, timeout=20) -> bool:
        """Cloudflare 等待 + 自动解决。

        完整流程：
        1. 等待 Cloudflare 自动验证（"正在验证..." 阶段，最多 10 秒）
        2. 如果自动通过 → 返回 True
        3. 如果出现 Turnstile 复选框 → 尝试点击
        4. 等待验证完成 → 返回结果

        必须在 _is_blocked() 返回 True 后调用。
        """
        if not self._is_cloudflare(tab):
            return False

        logger.info("[反爬] 检测到 Cloudflare challenge，等待自动验证...")

        # ── 阶段1：等待自动验证（Cloudflare 先显示 "正在验证..." spinner）──
        for i in range(10):
            tab.wait(1)
            if not self._is_cloudflare(tab):
                logger.info(f"[反爬] Cloudflare 自动验证通过（{i + 1}s）")
                return True

        # ── 阶段2：自动验证未通过，尝试点击 Turnstile 复选框 ──
        logger.info("[反爬] Cloudflare 自动验证未通过，尝试点击 Turnstile...")

        clicked = False

        # 方法1: DrissionPage CDP 穿透 closed shadow root
        try:
            checkbox = tab.ele('@type=checkbox', timeout=3)
            if checkbox:
                checkbox.click()
                logger.info("[反爬] CDP 穿透找到 checkbox 并点击")
                clicked = True
        except Exception:
            pass

        # 方法2: 坐标定位点击
        if not clicked:
            try:
                pos = tab.run_js("""
                    // Turnstile iframe 在 closed shadow root 内，
                    // 但容器 div (display:grid) 可访问
                    const divs = document.querySelectorAll('div');
                    for (const d of divs) {
                        const style = window.getComputedStyle(d);
                        const rect = d.getBoundingClientRect();
                        if (style.display === 'grid'
                            && rect.height > 50 && rect.height < 100
                            && rect.width > 200) {
                            return JSON.stringify({
                                x: rect.left, y: rect.top,
                                w: rect.width, h: rect.height
                            });
                        }
                    }
                    return null;
                """)
                if pos:
                    data = json.loads(pos)
                    click_x = int(data['x']) + 30
                    click_y = int(data['y'] + data['h'] / 2)
                    tab.actions.move(click_x, click_y, duration=0.3).click()
                    logger.info(f"[反爬] 坐标点击 Turnstile ({click_x}, {click_y})")
                    clicked = True
            except Exception as e:
                logger.warning(f"[反爬] Turnstile 坐标点击失败: {e}")

        if not clicked:
            logger.warning("[反爬] 未能找到 Turnstile 复选框")
            return False

        # ── 阶段3：等待点击后的验证完成 ──
        remaining = max(timeout - 10, 10)
        for i in range(remaining):
            tab.wait(1)
            if not self._is_cloudflare(tab):
                logger.info(f"[反爬] Cloudflare Turnstile 验证通过（点击后 {i + 1}s）")
                return True

        logger.warning("[反爬] Cloudflare Turnstile 点击后验证未通过")
        return False

    @staticmethod
    def _site_needs_proxy(url: str) -> bool:
        """检查 URL 对应的站点是否配置为直接使用代理"""
        from qbu_crawler.config import PROXY_SITES
        if not PROXY_SITES:
            return False
        try:
            from qbu_crawler.scrapers import get_site_key
            return get_site_key(url) in PROXY_SITES
        except ValueError:
            return False

    def _get_page(self, url: str):
        """导航到 URL，根据站点属性选择反爬策略。

        三层策略：
        1. 用户数据 + 代理（SITE_NEEDS_USER_DATA 站点）：Lock 串行，保留 cookie
        2. PROXY_SITES 直接代理（无用户数据时）
        3. 直连 → 被封降级代理（默认）
        """
        if self._use_user_data and self.SITE_NEEDS_USER_DATA:
            with self._user_data_lock:
                return self._get_page_user_data(url)
        return self._get_page_default(url)

    def _get_page_user_data(self, url: str):
        """用户数据模式：保留 cookie，代理轮换时重启 Chrome 但保留用户数据"""
        from qbu_crawler.proxy import get_proxy_pool
        from qbu_crawler.config import PROXY_MAX_RETRIES

        if not self._warmed_up:
            self._warm_up()
            self._warmed_up = True

        tab = self.browser.latest_tab
        tab.get(url)

        if not self._is_blocked(tab):
            if self._proxy:
                pool = get_proxy_pool()
                if pool:
                    pool.mark_good(self._proxy)
            return tab

        # Cloudflare: 等待自动验证 + 尝试点击 Turnstile，不需要换代理
        if self._wait_and_solve_cloudflare(tab):
            if self._proxy:
                pool = get_proxy_pool()
                if pool:
                    pool.mark_good(self._proxy)
            return tab

        # 被封 → 轮换代理，重启用户数据 Chrome（保留 cookie + 新 IP）
        pool = get_proxy_pool()
        if not pool:
            raise RuntimeError(
                f"用户数据模式下仍被封锁: {url}。"
                "请手动用 Chrome 访问目标站点刷新 cookie，"
                "或配置 PROXY_API_URL 启用代理池。"
            )

        for attempt in range(PROXY_MAX_RETRIES):
            new_proxy = pool.rotate(current_proxy=self._proxy)
            if not new_proxy:
                logger.error(f"[反爬] 无法获取代理 IP (attempt {attempt + 1})")
                continue
            if new_proxy == self._proxy:
                logger.warning(f"[反爬] 代理未变化 {new_proxy}，跳过")
                continue

            self._proxy = new_proxy
            logger.warning(
                f"[反爬] 被封 → 用户数据 + 代理 {new_proxy} "
                f"(attempt {attempt + 1}/{PROXY_MAX_RETRIES})"
            )
            self.browser = self._launch_with_user_data(proxy=new_proxy)
            self._warmed_up = False
            self._warm_up()
            self._warmed_up = True

            tab = self.browser.latest_tab
            tab.get(url)

            if not self._is_blocked(tab):
                pool.mark_good(new_proxy)
                return tab

        raise RuntimeError(
            f"用户数据模式下已尝试 {PROXY_MAX_RETRIES} 个代理均失败: {url}"
        )

    def _get_page_default(self, url: str):
        """默认策略：直连或 PROXY_SITES 代理，被封后轮换"""
        from qbu_crawler.proxy import get_proxy_pool
        from qbu_crawler.config import PROXY_MAX_RETRIES

        # PROXY_SITES: 首次直接走代理
        if not self._proxy and self._site_needs_proxy(url):
            pool = get_proxy_pool()
            if pool:
                proxy = pool.get()
                if proxy:
                    self._proxy = proxy
                    logger.info(f"[反爬] 站点配置直接走代理: {proxy}")
                    try:
                        self.browser.quit()
                    except Exception:
                        pass
                    self.browser = self._create_browser(proxy=proxy)

        tab = self.browser.latest_tab
        tab.get(url)

        if not self._is_blocked(tab):
            if self._proxy:
                pool = get_proxy_pool()
                if pool:
                    pool.mark_good(self._proxy)
            return tab

        # Cloudflare: 等待自动验证 + 尝试点击 Turnstile，不需要换代理
        if self._wait_and_solve_cloudflare(tab):
            if self._proxy:
                pool = get_proxy_pool()
                if pool:
                    pool.mark_good(self._proxy)
            return tab

        # 代理重试
        pool = get_proxy_pool()
        if not pool:
            raise RuntimeError(
                f"页面被反爬系统封锁: {url}。"
                "请配置 PROXY_API_URL 环境变量启用代理池。"
            )

        for attempt in range(PROXY_MAX_RETRIES):
            new_proxy = (
                pool.get() if (attempt == 0 and not self._proxy)
                else pool.rotate(current_proxy=self._proxy)
            )
            if not new_proxy:
                logger.error(f"[反爬] 无法获取代理 IP (attempt {attempt + 1})")
                continue
            if new_proxy == self._proxy and attempt > 0:
                logger.warning(f"[反爬] 代理未变化 {new_proxy}，跳过")
                continue

            self._proxy = new_proxy
            logger.warning(
                f"[反爬] Access Denied → 代理 {new_proxy} "
                f"(attempt {attempt + 1}/{PROXY_MAX_RETRIES})"
            )
            try:
                self.browser.quit()
            except Exception:
                pass
            self.browser = self._create_browser(proxy=new_proxy)
            tab = self.browser.latest_tab
            tab.get(url)

            if not self._is_blocked(tab):
                pool.mark_good(new_proxy)
                return tab

        raise RuntimeError(
            f"页面被反爬系统封锁，已尝试 {PROXY_MAX_RETRIES} 个代理均失败: {url}"
        )

    @staticmethod
    def _validate_product(result: dict, url: str):
        """校验抓取结果的关键字段，防止空数据或反爬页面数据被当作成功保存"""
        product = result.get("product", {})
        name = product.get("name") or ""
        sku = product.get("sku")
        price = product.get("price")

        # name 和 sku 都为空 → 完全没提取到数据
        if not name and not sku:
            raise RuntimeError(
                f"抓取结果无效（name 和 sku 均为空），页面可能未正确加载: {url}"
            )
        # name 是反爬页面特征 → Cloudflare/Akamai 页面被当产品提取了
        blocked_names = {"waltons.com", "basspro.com", "meatyourmaker.com",
                         "access denied", "just a moment", "请稍候", "执行安全验证"}
        if name.lower().strip() in blocked_names:
            raise RuntimeError(
                f"抓取结果无效（name 为反爬页面标识 '{name}'），Cloudflare/Akamai 未通过: {url}"
            )
        # 有 name 但没有 sku 和 price → 可能是不完整的页面
        if name and not sku and price is None:
            raise RuntimeError(
                f"抓取结果不完整（有 name 但 sku 和 price 均为空），页面可能未正确加载: {url}"
            )

    def _increment_and_delay(self, tab):
        """递增抓取计数并执行随机延迟"""
        self._scrape_count += 1
        if REQUEST_DELAY:
            tab.wait(REQUEST_DELAY[0], REQUEST_DELAY[1])

    def _process_review_images(self, reviews: list) -> list:
        """下载评论图片到 MinIO，将 BV URL 替换为 MinIO URL"""
        from qbu_crawler.minio_client import upload_image

        for review in reviews:
            bv_urls = review.get("images", [])
            if not bv_urls:
                review["images"] = None
                continue
            minio_urls = []
            for url in bv_urls:
                minio_url = upload_image(url)
                if minio_url:
                    minio_urls.append(minio_url)
            review["images"] = json.dumps(minio_urls) if minio_urls else None
        return reviews

    @staticmethod
    def _to_float(val) -> float | None:
        if val is None:
            return None
        try:
            return float(val)
        except (ValueError, TypeError):
            return None

    @staticmethod
    def _to_int(val) -> int | None:
        if val is None:
            return None
        try:
            return int(val)
        except (ValueError, TypeError):
            return None

    def close(self):
        # DrissionPage 默认 quit() 只发 CDP Browser.close + detach WebSocket，不杀进程，
        # Chrome 有"后台保持运行"机制后进程继续 LISTENING，下次启动会探测到半死僵尸。
        # 必须 force=True 走 SystemInfo.getProcessInfo + psutil.Process.kill() 路径。
        try:
            self.browser.quit(force=True, timeout=5)
        except Exception:
            try:
                self.browser.quit()
            except Exception:
                pass
        # 用户数据模式：端口→PID 强杀 + user-data-dir 核爆（清 renderer/helper 残留）。
        # 不核爆 renderer 的话，下一次 Popen 新 Chrome 时会被它们持有的 profile 锁 IPC 走。
        if self._use_user_data:
            self._kill_user_data_chrome(self._USER_DATA_PORT)
