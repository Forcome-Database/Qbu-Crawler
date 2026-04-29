import json
import logging
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
import uuid
from urllib.parse import urlparse

from DrissionPage import Chromium, ChromiumOptions
from qbu_crawler.config import (
    HEADLESS, PAGE_LOAD_TIMEOUT, NO_IMAGES,
    RETRY_TIMES, RETRY_INTERVAL, REQUEST_DELAY, RESTART_EVERY,
    CHROME_USER_DATA_PATH, CHROME_PROFILE_ROT_THRESHOLD, CHROME_USER_DATA_SYNC_FILES,
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
    # ── 站点级属性（子类可覆盖）──
    SITE_LOAD_MODE: str = "eager"       # 页面加载模式
    SITE_NEEDS_USER_DATA: bool = False  # 是否需要 Chrome 用户数据模式
    SITE_RESTART_SAFE: bool = True      # 浏览器重启是否安全（不丢关键 cookie）
    # 站点专属请求间隔（秒），None 时用全局 REQUEST_DELAY
    # 用途：basspro 等严格反爬站点需要更长停顿模拟真人节奏
    SITE_REQUEST_DELAY: tuple[int, int] | None = None

    # ⚠ 架构关键（2026-04-22 重构）：
    # 废弃固定 _USER_DATA_PORT=19222 + 共享 CHROME_USER_DATA_PATH 的模型。
    # Windows Chrome 的 Single-Instance 互斥量 key = hash(user-data-dir)，
    # 跨 session 残留的 Chrome 进程（含子进程）持有互斥量，新 Popen IPC 自退。
    # 无论怎么 kill，互斥量释放时机不可控（Windows handle 继承 / Chrome 重生等）。
    # 根治方案：每个 scraper 实例用唯一 user-data-dir + 随机端口，
    # 互斥量 key 不同 → 完全不存在冲突可能，kill/lock 路径都不再是关键路径。
    _user_data_lock = threading.Lock()

    def __init__(self):
        if HEADLESS and not _has_display():
            _ensure_virtual_display()
        self._use_user_data = bool(CHROME_USER_DATA_PATH) and self.SITE_NEEDS_USER_DATA
        self._proxy = None  # 当前使用的代理 (ip:port)
        self._warmed_up = False
        self._session_profile_dirty = False
        # Session 隔离：每实例独立 user-data-dir + port
        self._session_user_data_dir: str | None = None
        self._session_port: int | None = None
        if self._use_user_data:
            self._proxy = self._get_initial_proxy()
            self._cleanup_stale_session_profiles()
            self._session_user_data_dir = self._allocate_session_profile()
            self._session_port = self._allocate_free_port()
            logger.info(
                f"[Chrome] 准备启动独立实例: port={self._session_port}, "
                f"user-data-dir={self._session_user_data_dir}, proxy={'on' if self._proxy else 'off'}"
            )
            self.browser = self._launch_with_user_data(
                user_data_dir=self._session_user_data_dir,
                port=self._session_port,
                proxy=self._proxy,
            )
            logger.info(
                f"[Chrome] 独立实例启动完成: port={self._session_port}, "
                f"user-data-dir={self._session_user_data_dir}"
            )
        else:
            self.browser = self._create_browser()
        self._scrape_count = 0

    @classmethod
    def _cleanup_stale_session_profiles(cls):
        """清扫历史残留的 _sess_* 目录（PID 已死的）。
        上次 Ctrl+C 没跑到 close() 时会留下 session 目录，下次启动清掉。"""
        if not CHROME_USER_DATA_PATH:
            return
        parent = os.path.dirname(CHROME_USER_DATA_PATH) or "."
        base_name = os.path.basename(CHROME_USER_DATA_PATH)
        prefix = f"{base_name}_sess_"
        if not os.path.isdir(parent):
            return
        try:
            import psutil
            have_psutil = True
        except ImportError:
            have_psutil = False
        for name in os.listdir(parent):
            if not name.startswith(prefix):
                continue
            # 从目录名解析 PID：{base}_sess_{pid}_{uuid}
            try:
                pid = int(name[len(prefix):].split('_')[0])
            except (ValueError, IndexError):
                continue
            if have_psutil and psutil.pid_exists(pid):
                continue  # PID 活着，可能是兄弟 scraper，保留
            stale_dir = os.path.join(parent, name)
            try:
                shutil.rmtree(stale_dir, ignore_errors=True)
                logger.info(f"[Chrome] 清理陈旧 session（PID {pid} 已死）: {name}")
            except Exception as e:
                logger.warning(f"[Chrome] 清理陈旧 session {name} 失败: {e}")

    @classmethod
    def _allocate_session_profile(cls) -> str:
        """创建本实例专属的 user-data-dir，从 CHROME_USER_DATA_PATH 复制关键文件。
        目录唯一化 → Chrome 命名互斥量 key 唯一 → 无跨 session 冲突可能。"""
        parent = os.path.dirname(CHROME_USER_DATA_PATH) or "."
        base_name = os.path.basename(CHROME_USER_DATA_PATH)
        session_id = f"sess_{os.getpid()}_{uuid.uuid4().hex[:8]}"
        session_dir = os.path.join(parent, f"{base_name}_{session_id}")
        os.makedirs(os.path.join(session_dir, "Default"), exist_ok=True)
        if os.path.isdir(CHROME_USER_DATA_PATH):
            for sub, name in CHROME_USER_DATA_SYNC_FILES:
                rel = os.path.join(sub, name) if sub else name
                src = os.path.join(CHROME_USER_DATA_PATH, rel)
                dst = os.path.join(session_dir, rel)
                if not os.path.isfile(src):
                    continue
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                try:
                    shutil.copy2(src, dst)
                except Exception as e:
                    logger.warning(f"[Chrome] session 复制 {rel} 失败: {e}")
        logger.info(f"[Chrome] 本实例独立 user-data-dir: {session_dir}")
        return session_dir

    @staticmethod
    def _allocate_free_port() -> int:
        """OS 随机分配空闲端口"""
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(('127.0.0.1', 0))
            return s.getsockname()[1]

    def _create_browser(self, proxy: str | None = None) -> Chromium:
        """创建浏览器实例，可选代理"""
        options = self._build_options()
        if proxy:
            options.set_argument(f'--proxy-server=http://{proxy}')
        return Chromium(options)

    @staticmethod
    def _attach_browser(port: int, ws_timeout: float = 5.0) -> Chromium:
        old_timeout = socket.getdefaulttimeout()
        socket.setdefaulttimeout(ws_timeout)
        try:
            return Chromium(port)
        finally:
            socket.setdefaulttimeout(old_timeout)

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
        """按 cmdline 精确识别用户数据 Chrome **主进程**（严格：port + user-data-dir 都要匹配）。
        用途：_launch_with_user_data_locked 里判断"我们 Popen 的那个主进程是否还活着"。

        ⚠ 注意：这个函数**不会**匹配 renderer / utility / gpu-process 等子进程
        （子进程只有 --user-data-dir 没有 --remote-debugging-port）。清僵尸请用
        _find_chrome_pids_by_user_data，否则会放过持 Single-Instance 互斥量的子进程。"""
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
    def _find_chrome_pids_by_user_data(cls, user_data_dir: str | None = None) -> list[int]:
        """按 --user-data-dir 宽匹配所有 chrome.exe（主进程 + 所有子进程 + 后台进程）。
        默认匹配 CHROME_USER_DATA_PATH；传参时匹配指定目录（本 session 场景）。

        路径规范化处理 C:\\ vs c:/ vs 短路径名 vs 尾部斜杠等 Windows 变体。"""
        pids = []
        target_dir = user_data_dir or CHROME_USER_DATA_PATH
        if not target_dir:
            return pids
        try:
            import psutil
        except ImportError:
            return pids
        try:
            target = os.path.normcase(os.path.normpath(os.path.abspath(target_dir)))
        except Exception:
            return pids
        for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
            try:
                name = (proc.info.get('name') or '').lower()
                if name not in ('chrome.exe', 'chrome'):
                    continue
                cmdline = proc.info.get('cmdline') or []
                matched = False
                for arg in cmdline:
                    if not arg.startswith('--user-data-dir='):
                        continue
                    path_val = arg.split('=', 1)[1].strip().strip('"').strip("'")
                    try:
                        arg_path = os.path.normcase(
                            os.path.normpath(os.path.abspath(path_val))
                        )
                    except Exception:
                        continue
                    if arg_path == target:
                        matched = True
                        break
                if matched:
                    pids.append(proc.info['pid'])
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        return pids

    @classmethod
    def _kill_user_data_chrome(cls, port: int, user_data_dir: str | None = None):
        """杀指定 user-data-dir 关联的 Chrome 进程。
        当每 session 独立目录时，本函数只杀本 session 内的 Chrome（代理轮换时）。
        不再用于清跨 session 僵尸（那是架构层面通过唯一目录解决的）。"""
        # 1. CDP graceful quit —— 仅在端口有 Chrome 时
        if cls._find_pids_on_port(port):
            try:
                browser = cls._attach_browser(port)
                browser.quit(force=True, timeout=5)
            except Exception:
                pass

        # 2. psutil 按 user_data_dir 匹配 kill
        target_dir = user_data_dir or CHROME_USER_DATA_PATH
        if not target_dir:
            return
        try:
            import psutil
            for attempt in range(3):
                pids = cls._find_chrome_pids_by_user_data(target_dir)
                if not pids:
                    break
                for pid in pids:
                    try:
                        p = psutil.Process(pid)
                        for child in p.children(recursive=True):
                            try: child.kill()
                            except Exception: pass
                        p.kill()
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        pass
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

    @staticmethod
    def _clean_singleton_locks(user_data_dir: str | None = None):
        """清理指定 user-data-dir 下的 Chrome 单实例锁文件。默认清 CHROME_USER_DATA_PATH。
        Chrome 异常退出后锁文件残留 → 新 Chrome IPC 给"锁持有者"立刻退出。
        注意：文件级清锁只解决部分场景；Windows 命名互斥量冲突不是清文件能解决的，
        根治在于每 session 用独立 user-data-dir（互斥量 key 不同）。"""
        target = user_data_dir or CHROME_USER_DATA_PATH
        if not target:
            return
        for name in ('SingletonLock', 'SingletonCookie', 'SingletonSocket'):
            path = os.path.join(target, name)
            try:
                if os.path.lexists(path):
                    os.remove(path)
            except Exception as e:
                logger.warning(f"[启动] 清理 {name} 失败: {e}")

    # ── Profile 腐化自愈 ──
    _ROT_STREAK_FILE = ".qbu_rot_streak"

    @classmethod
    def _rot_streak_path(cls) -> str | None:
        if not CHROME_USER_DATA_PATH:
            return None
        return os.path.join(CHROME_USER_DATA_PATH, cls._ROT_STREAK_FILE)

    @classmethod
    def _read_rot_streak(cls) -> int:
        path = cls._rot_streak_path()
        if not path:
            return 0
        try:
            with open(path, "r", encoding="utf-8") as f:
                return int((f.read() or "0").strip())
        except (FileNotFoundError, ValueError, OSError):
            return 0

    @classmethod
    def _write_rot_streak(cls, n: int):
        path = cls._rot_streak_path()
        if not path:
            return
        try:
            os.makedirs(CHROME_USER_DATA_PATH, exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                f.write(str(max(0, n)))
        except OSError as e:
            logger.warning(f"[profile] 写 rot streak 失败: {e}")

    @classmethod
    def _maybe_rebuild_rotten_profile(cls):
        """专属 profile 连续 N 次用完所有代理仍无法解封 → 认定 _abck 腐化，
        删目录让下次 _seed_chrome_user_data 从 SEED 重建。
        调用点：_launch_with_user_data_locked 入口，所以删目录时 Chrome 尚未起。
        在 _user_data_lock 持锁下调用，无并发问题。"""
        if not CHROME_USER_DATA_PATH or CHROME_PROFILE_ROT_THRESHOLD <= 0:
            return
        streak = cls._read_rot_streak()
        if streak < CHROME_PROFILE_ROT_THRESHOLD:
            return
        logger.error(
            f"[profile] 检测到专属 profile 连续 {streak} 次被封（>= 阈值 "
            f"{CHROME_PROFILE_ROT_THRESHOLD}），判定为腐化。"
            f"删除 {CHROME_USER_DATA_PATH} 并从 SEED 重建..."
        )
        # 清理 base 目录下 Chrome 相关进程；session 目录是独立的，不受影响
        # 注意：base 目录本身不应该有 Chrome 在用（session 都是 base_sess_*），
        # 但以防用户手动用过 base，防御性 kill 一下
        cls._kill_user_data_chrome(port=0, user_data_dir=CHROME_USER_DATA_PATH)
        try:
            shutil.rmtree(CHROME_USER_DATA_PATH, ignore_errors=False)
        except Exception as e:
            logger.error(
                f"[profile] 删除腐化 profile 失败: {e}（可能仍有 Chrome 进程占用，"
                "下次启动再试）"
            )
            return
        # 重新 seed：_seed_chrome_user_data 自身做目录存在性检查
        from qbu_crawler import config as _cfg
        _cfg._seed_chrome_user_data()
        logger.warning("[profile] 腐化 profile 已重建，streak 计数自动归零（文件已被删除）")

    @classmethod
    def _launch_with_user_data(
        cls,
        user_data_dir: str,
        port: int,
        proxy: str | None = None,
    ) -> Chromium:
        """使用独立 user-data-dir + 独立 port 启动 Chrome。
        每 scraper 实例一套（唯一目录 + 随机端口），根治 SingletonLock 跨 session 冲突。
        锁保留用于同实例内代理轮换时的串行启停。"""
        with cls._user_data_lock:
            return cls._launch_with_user_data_locked(
                user_data_dir=user_data_dir, port=port, proxy=proxy,
            )

    @classmethod
    def _launch_with_user_data_locked(
        cls,
        user_data_dir: str,
        port: int,
        proxy: str | None = None,
    ) -> Chromium:
        # 腐化自愈（影响 seed 源 CHROME_USER_DATA_PATH，下次 allocate_session 时从新 base 复制）
        cls._maybe_rebuild_rotten_profile()

        # user_data_dir 是本 session 专属目录（首次调用由 _allocate_session_profile 创建；
        # 代理切换时复用该目录）。**没有跨 session 冲突**，无需 reuse 分支、无需 kill 旧 Chrome。
        # 仅为防御性：如果同一 session 内之前 Popen 的 Chrome 还在跑（如代理轮换），先杀它。
        cls._kill_user_data_chrome(port=port, user_data_dir=user_data_dir)
        cls._clean_singleton_locks(user_data_dir)

        chrome_path = _find_chrome()
        logger.info(
            f"[启动] 准备 Popen Chrome: port={port}, "
            f"user-data-dir={user_data_dir}, proxy={'on' if proxy else 'off'}"
        )
        args = [
            chrome_path,
            f'--remote-debugging-port={port}',
            f'--user-data-dir={user_data_dir}',
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
        args.append('--restore-last-session=false')

        # 捕获 Chrome stderr 到临时 log 文件，失败时把内容贴进异常信息，便于诊断
        stderr_log_path = os.path.join(user_data_dir, ".qbu_chrome_stderr.log")
        stderr_fh = None
        try:
            stderr_fh = open(stderr_log_path, 'wb')
        except Exception:
            pass
        subprocess.Popen(
            args,
            stdout=subprocess.DEVNULL,
            stderr=stderr_fh or subprocess.DEVNULL,
        )
        logger.info(f"[启动] 已 Popen Chrome，等待端口就绪: port={port}")
        last_err = None
        dead_streak = 0
        listening_logged = False
        for attempt in range(40):
            time.sleep(1)
            if not cls._find_pids_on_port(port):
                listening_logged = False
                # 严格匹配：我们 Popen 的主 chrome.exe（port + user_data_dir）是否还活着
                chrome_alive = bool(cls._find_chrome_pid_by_port_and_dir(port, user_data_dir))
                if chrome_alive:
                    last_err = f"Chrome 进程存活但尚未 LISTENING (attempt {attempt + 1})"
                    dead_streak = 0
                else:
                    dead_streak += 1
                    last_err = f"Popen 的 Chrome 已退出 (attempt {attempt + 1})"
                    if dead_streak >= 3:
                        logger.warning(f"[启动] {last_err}，重清 SingletonLock 重新 Popen")
                        cls._clean_singleton_locks(user_data_dir)
                        subprocess.Popen(
                            args,
                            stdout=subprocess.DEVNULL,
                            stderr=stderr_fh or subprocess.DEVNULL,
                        )
                        dead_streak = 0
                continue
            try:
                if not listening_logged:
                    logger.info(f"[启动] 端口已监听，开始 attach: port={port}")
                    listening_logged = True
                logger.info(f"[启动] attach_browser 开始: port={port}")
                browser = cls._attach_browser(port)
                logger.info(f"[启动] attach_browser 成功: port={port}")
                logger.info(f"[启动] cleanup_tabs 开始: port={port}")
                cls._cleanup_tabs(browser)
                logger.info(f"[启动] cleanup_tabs 完成: port={port}")
                logger.info(f"[启动] probe_browser_alive 开始: port={port}")
                if not cls._probe_browser_alive(browser):
                    last_err = "page target 未就绪"
                    continue
                logger.info(f"[启动] probe_browser_alive 成功: port={port}")
                if stderr_fh:
                    try: stderr_fh.close()
                    except Exception: pass
                return browser
            except Exception as e:
                last_err = repr(e)
                continue
        # 启动失败：读 stderr log 附到异常里
        if stderr_fh:
            try: stderr_fh.close()
            except Exception: pass
        chrome_msg = cls._tail_chrome_stderr(stderr_log_path, max_lines=20)
        # Chrome 启动失败本身就是 profile 可能腐化的信号
        cls._write_rot_streak(cls._read_rot_streak() + 1)
        detail = f"\n--- Chrome stderr (tail) ---\n{chrome_msg}" if chrome_msg else ""
        raise RuntimeError(
            f"Chrome with user data failed to start on port {port}: {last_err}{detail}"
        )

    @staticmethod
    def _tail_chrome_stderr(path: str, max_lines: int = 20) -> str:
        """读取 Chrome stderr 最后 N 行，用于诊断 Chrome 为何启动失败（IPC? crash?）"""
        try:
            if not os.path.isfile(path) or os.path.getsize(path) == 0:
                return ""
            with open(path, 'rb') as f:
                data = f.read().decode('utf-8', errors='replace').strip()
            lines = data.splitlines()
            return "\n".join(lines[-max_lines:])
        except Exception:
            return ""

    @classmethod
    def _find_chrome_pid_by_port_and_dir(cls, port: int, user_data_dir: str) -> list[int]:
        """严格匹配：同时带 --remote-debugging-port={port} 和 --user-data-dir={user_data_dir}
        的主 chrome.exe。用于判断我们 Popen 的主进程是否还活着。"""
        pids = []
        try:
            import psutil
        except ImportError:
            return pids
        try:
            target = os.path.normcase(os.path.normpath(os.path.abspath(user_data_dir)))
        except Exception:
            return pids
        marker_port = f'--remote-debugging-port={port}'
        for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
            try:
                name = (proc.info.get('name') or '').lower()
                if name not in ('chrome.exe', 'chrome'):
                    continue
                cmdline = proc.info.get('cmdline') or []
                joined = ' '.join(cmdline)
                if marker_port not in joined:
                    continue
                for arg in cmdline:
                    if not arg.startswith('--user-data-dir='):
                        continue
                    path_val = arg.split('=', 1)[1].strip().strip('"').strip("'")
                    try:
                        arg_path = os.path.normcase(os.path.normpath(os.path.abspath(path_val)))
                    except Exception:
                        continue
                    if arg_path == target:
                        pids.append(proc.info['pid'])
                        break
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        return pids

    @staticmethod
    def _cleanup_tabs(browser):
        """关闭多余标签，只保留一个。防止用户数据 Chrome 会话恢复导致标签堆积。

        get_tabs() 返回 MixTab 对象列表，对象本身就有 close()。之前误用
        browser.get_tab(obj) 二次查询，把对象塞进期望 str/int 的参数，
        行为未定义，可能把 page-type target 全部关光，导致后续
        browser.latest_tab → self.tab_ids[0] 抛 IndexError。
        """
        old_timeout = socket.getdefaulttimeout()
        try:
            socket.setdefaulttimeout(5.0)
            logger.info("[清理] get_tabs 开始")
            tabs = browser.get_tabs()
            logger.info(f"[清理] get_tabs 完成: 共 {len(tabs)} 个")
        except Exception as e:
            logger.warning(f"[清理] get_tabs 失败: {e}")
            return
        finally:
            socket.setdefaulttimeout(old_timeout)
        if len(tabs) <= 1:
            return
        old_timeout = socket.getdefaulttimeout()
        try:
            socket.setdefaulttimeout(5.0)
            logger.info("[清理] new_tab 开始")
            fresh = browser.new_tab('about:blank')
            logger.info(f"[清理] new_tab 完成: fresh_id={getattr(fresh, 'tab_id', None)}")
        except Exception as e:
            logger.warning(f"[清理] new_tab 失败，跳过清理: {e}")
            return
        finally:
            socket.setdefaulttimeout(old_timeout)
        fresh_id = getattr(fresh, 'tab_id', None)
        closed = 0
        for idx, tab in enumerate(tabs, start=1):
            try:
                if fresh_id and getattr(tab, 'tab_id', None) == fresh_id:
                    continue
                tab_id = getattr(tab, 'tab_id', None)
                old_timeout = socket.getdefaulttimeout()
                socket.setdefaulttimeout(3.0)
                logger.info(f"[清理] 关闭旧标签开始: index={idx}, tab_id={tab_id}")
                tab.close()
                logger.info(f"[清理] 关闭旧标签完成: index={idx}, tab_id={tab_id}")
                closed += 1
            except Exception as e:
                logger.warning(
                    f"[清理] 关闭旧标签失败: index={idx}, "
                    f"tab_id={getattr(tab, 'tab_id', None)}, err={e}"
                )
            finally:
                socket.setdefaulttimeout(old_timeout)
        logger.info(f"[清理] 关闭 {closed} 个旧标签（共 {len(tabs)} 个），保留新建 about:blank")

    @staticmethod
    def _probe_browser_alive(browser) -> bool:
        """健康探测：确认 Chrome CDP 既能握手又能真正执行操作。
        僵尸场景：端口残留、Chromium(port) 成功，但 new_tab/latest_tab 立刻 refused。
        探测逻辑：若无 page target 就开一个 about:blank；然后读 latest_tab.url。
        任一步失败 → 返回 False，上层重启 Chrome。"""
        old_timeout = socket.getdefaulttimeout()
        try:
            socket.setdefaulttimeout(5.0)
            if browser.tabs_count == 0:
                browser.new_tab('about:blank')
            # latest_tab + .url 会走一次 CDP Target.getTargets + Runtime
            _ = browser.latest_tab.url
            return True
        except Exception as e:
            logger.warning(f"[启动] 浏览器健康探测失败: {e}")
            return False
        finally:
            socket.setdefaulttimeout(old_timeout)

    def _warm_up(self):
        """访问站点首页完成反爬 challenge（如 Akamai _abck cookie）。
        子类可覆盖提供站点特定的预热逻辑。默认不做任何事。"""
        return False

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
            self._session_profile_dirty = bool(self._warm_up()) or self._session_profile_dirty
            self._warmed_up = True

        tab = self.browser.latest_tab
        tab.get(url)

        if not self._is_blocked(tab):
            if self._proxy:
                pool = get_proxy_pool()
                if pool:
                    pool.mark_good(self._proxy)
            type(self)._write_rot_streak(0)
            self._session_profile_dirty = True
            return tab

        # Cloudflare: 等待自动验证 + 尝试点击 Turnstile，不需要换代理
        if self._wait_and_solve_cloudflare(tab):
            if self._proxy:
                pool = get_proxy_pool()
                if pool:
                    pool.mark_good(self._proxy)
            type(self)._write_rot_streak(0)
            self._session_profile_dirty = True
            return tab

        # 被封 → 轮换代理，重启用户数据 Chrome（保留 cookie + 新 IP）
        pool = get_proxy_pool()
        if not pool:
            type(self)._write_rot_streak(type(self)._read_rot_streak() + 1)
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
            self.browser = self._launch_with_user_data(
                user_data_dir=self._session_user_data_dir,
                port=self._session_port,
                proxy=new_proxy,
            )
            self._warmed_up = False
            self._session_profile_dirty = bool(self._warm_up()) or self._session_profile_dirty
            self._warmed_up = True

            tab = self.browser.latest_tab
            tab.get(url)

            if not self._is_blocked(tab):
                pool.mark_good(new_proxy)
                type(self)._write_rot_streak(0)
                self._session_profile_dirty = True
                return tab

        # 所有代理都过不去 = profile 的 _abck 彻底烂掉；streak++
        # 达到阈值后下次 _launch_with_user_data_locked 会自动删目录 reseed
        type(self)._write_rot_streak(type(self)._read_rot_streak() + 1)
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
        """递增抓取计数并执行随机延迟
        优先用 SITE_REQUEST_DELAY，回退到全局 REQUEST_DELAY"""
        self._scrape_count += 1
        delay = self.SITE_REQUEST_DELAY or REQUEST_DELAY
        if delay:
            tab.wait(delay[0], delay[1])

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

    # ── 异步注入式 promo 弹窗清理 ──
    # 站点（如 basspro）会在产品页加载几秒后，由第三方 SaaS（Listrak/Bronto/Privy/
    # Klaviyo 等）异步注入一个 lightbox iframe + 全屏 overlay 做 newsletter 订阅或
    # exit-intent。这个 iframe 的 sandbox 通常带 `allow-top-navigation`，意味着
    # 它内部脚本可以触发 parent reload；恰好撞到 DrissionPage 的 tab.run_js
    # 会抛 ContextLostError ("The page is refreshed.")。
    # 必须在重 JS 操作之前主动移除，且在 wait 间隙重复（mousemove/scroll 后会再注入）。
    _PROMO_OVERLAY_JS = """
        let removed = 0;
        // 1) lightbox / exit-intent popup iframe
        document.querySelectorAll(
            'iframe[id*="lightbox" i], iframe[title*="Email" i], '
            + 'iframe[title*="Exit Intent" i], iframe[src*="privy" i], '
            + 'iframe[src*="klaviyo" i], iframe[src*="listrak" i], '
            + 'iframe[src*="justuno" i], iframe[src*="bronto" i]'
        ).forEach(f => { try { f.remove(); removed++; } catch(e) {} });
        // 2) 全屏 fixed overlay（z-index >= 99 + 占据 ≥ 50% 视口 + 命名疑似弹窗）
        document.querySelectorAll('div').forEach(d => {
            try {
                const cs = getComputedStyle(d);
                const z = parseInt(cs.zIndex || '0', 10);
                if (cs.position === 'fixed' && z >= 99
                    && d.offsetWidth  >= window.innerWidth  * 0.5
                    && d.offsetHeight >= window.innerHeight * 0.5
                    && /lightbox|popup|overlay|modal|fancybox/i.test(
                        (d.className || '') + ' ' + (d.id || ''))) {
                    d.remove(); removed++;
                }
            } catch(e) {}
        });
        // 3) popup 常把 body 锁成 overflow:hidden，解锁
        if (document.body) document.body.style.overflow = '';
        return removed;
    """

    def _kill_promo_overlays(self, tab, max_attempts: int = 3):
        """物理移除异步注入的 newsletter / exit-intent / lightbox 弹窗。
        必须在 tab.run_js 重操作之前调用，且要在 wait 间隙重复。"""
        for _ in range(max_attempts):
            try:
                n = tab.run_js(self._PROMO_OVERLAY_JS)
                if n and int(n) > 0:
                    tab.wait(0.5, 1)
                    continue
                return
            except Exception:
                return

    def close(self):
        # DrissionPage 默认 quit() 只发 CDP Browser.close + detach WebSocket，不杀进程；
        # Chrome 后台保持运行机制让进程继续 LISTENING，必须 force=True 走 SystemInfo 路径。
        try:
            self.browser.quit(force=True, timeout=5)
        except Exception:
            try:
                self.browser.quit()
            except Exception:
                pass
        if self._use_user_data:
            # 杀本 session 的 Chrome 及其子进程（按本 session 的 user-data-dir 匹配，
            # 不影响其它并行 session）
            if self._session_port is not None:
                self._kill_user_data_chrome(
                    port=self._session_port,
                    user_data_dir=self._session_user_data_dir,
                )
            if (
                self._session_profile_dirty
                and CHROME_USER_DATA_PATH
                and self._session_user_data_dir
                and os.path.isdir(self._session_user_data_dir)
            ):
                cookies_path = os.path.join(self._session_user_data_dir, "Default", "Cookies")
                if os.path.isfile(cookies_path):
                    try:
                        has_cookies = os.path.getsize(cookies_path) > 0
                    except OSError:
                        has_cookies = False
                else:
                    has_cookies = False
                if has_cookies:
                    for sub, name in CHROME_USER_DATA_SYNC_FILES:
                        rel = os.path.join(sub, name) if sub else name
                        src = os.path.join(self._session_user_data_dir, rel)
                        if not os.path.isfile(src):
                            continue
                        dst = os.path.join(CHROME_USER_DATA_PATH, rel)
                        os.makedirs(os.path.dirname(dst), exist_ok=True)
                        tmp_dst = f"{dst}.tmp.{uuid.uuid4().hex}"
                        try:
                            shutil.copy2(src, tmp_dst)
                            os.replace(tmp_dst, dst)
                        except Exception as e:
                            try:
                                if os.path.exists(tmp_dst):
                                    os.remove(tmp_dst)
                            except OSError:
                                pass
                            logger.warning(f"[Chrome] 回写 {rel} 失败: {e}")
            # 删本 session 的目录，避免磁盘积累
            if self._session_user_data_dir and os.path.isdir(self._session_user_data_dir):
                try:
                    shutil.rmtree(self._session_user_data_dir, ignore_errors=True)
                    logger.info(f"[Chrome] 删除 session 目录: {self._session_user_data_dir}")
                except Exception as e:
                    logger.warning(f"[Chrome] 删除 session 目录失败: {e}")
