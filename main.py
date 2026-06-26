"""
东营市继续教育平台 - 学习进度辅助管理程序 v1.0
功能：播放状态监测 → 章节进度识别 → 弹窗交互辅助 → 异常恢复
"""

import sys
import os
import time
import itertools
import subprocess
from pathlib import Path

def ensure_deps():
    try:
        import selenium
        import webdriver_manager
    except ImportError:
        print("[初始化] 正在安装 selenium，请稍候...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "selenium", "webdriver-manager", "-q"])
        print("[初始化] 安装完成！\n")

print("[启动] 正在检查运行环境...", flush=True)
try:
    ensure_deps()
except Exception as e:
    print("\n[错误] 依赖安装失败，浏览器不会启动。")
    print(f"[错误详情] {e}")
    print("\n请确认：1. 已安装 Python；2. 网络可访问；3. 没有被杀毒软件拦截。")
    input("\n按 Enter 退出...")
    sys.exit(1)

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.edge.service import Service as EdgeService
from selenium.webdriver.edge.options import Options as EdgeOptions
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.firefox.service import Service as FirefoxService
from selenium.webdriver.firefox.options import Options as FirefoxOptions
from selenium.common.exceptions import (
    NoSuchElementException, ElementNotInteractableException, WebDriverException
)

URL           = "https://www.jxjydongying.cn/"
POLL_INTERVAL = 2.0   
ANSWER_DELAY  = 0.8   
SUBMIT_DELAY  = 1.5   
DONE_DELAY    = 2.0   
NEXT_DELAY    = 3.0   

BANNER = """
╔═══════════════════════════════════════════════╗
║   东营继续教育 - 学习进度辅助管理程序 v1.0     ║
║   进度监测 → 播放恢复 → 章节导航 → 弹窗辅助     ║
╚═══════════════════════════════════════════════╝
"""

# 全局记忆核心：记录每道题已经尝试过的答案组合
tried_answers_history = {}
last_quiz_time = 0
last_quiz_qkey = ""

def log(msg):
    print(f"  [{time.strftime('%H:%M:%S')}] {msg}")

# ── 核心侦测引擎 ──────────────────────
CHECK_PLAYING_JS = """
try {
    if (document.querySelector('.vjs-playing, .bplayer-playing, [title="暂停"], [aria-label="暂停"], .playing')) {
        return true;
    }
    function getV(root) {
        var arr = [];
        if(!root) return arr;
        var els = root.querySelectorAll('*');
        for(var i=0; i<els.length; i++) {
            if(els[i].tagName === 'VIDEO') arr.push(els[i]);
            if(els[i].shadowRoot) arr = arr.concat(getV(els[i].shadowRoot));
        }
        return arr;
    }
    var vs = getV(document);
    for(var i=0; i<vs.length; i++) {
        if(!vs[i].paused && !vs[i].ended && vs[i].offsetWidth > 10) return true;
    }
    return false;
} catch(e) { return false; }
"""

def generate_all_guesses(option_texts, is_multi):
    """根据选项生成所有可能的答案组合，按优先级排序"""
    count = len(option_texts)
    if count == 0: return []
    
    guesses = []
    
    # 判断题逻辑：优先选含有对/正确字眼的选项
    if count <= 2 and any(word in text for text in option_texts for word in ["正确", "错误", "对", "错", "是", "否"]):
        for i, t in enumerate(option_texts):
            if any(w in t for w in ["对", "正确", "是"]):
                guesses.append([i])
        for i in range(count):
            if [i] not in guesses: guesses.append([i])
        return guesses

    if is_multi:
        # 多选优先级 1：去掉最短的，其余全选
        if count > 2:
            min_len = min(len(t) for t in option_texts)
            p1 = [i for i, t in enumerate(option_texts) if len(t) > min_len]
            if p1: guesses.append(p1)
        
        # 多选优先级 2：全部都选
        p2 = list(range(count))
        if p2 not in guesses: guesses.append(p2)
        
        # 多选优先级 3：穷举所有可能的组合（从多到少）
        for r in range(count - 1, 0, -1):
            for combo in itertools.combinations(range(count), r):
                c = list(combo)
                if c not in guesses:
                    guesses.append(c)
        return guesses

    # 单选题逻辑
    # 优先级 1：选描述最长的（通常是最完整的）
    max_len = max(len(t) for t in option_texts)
    p1 = next((i for i, t in enumerate(option_texts) if len(t) == max_len), 0)
    guesses.append([p1])
    
    # 优先级 2：穷举其他所有单项
    for i in range(count):
        if [i] not in guesses:
            guesses.append([i])
            
    return guesses

def _first_existing_path(paths):
    for path in paths:
        if path and Path(path).exists():
            return str(path)
    return None

def _local_driver_path(name):
    base_dir = Path(__file__).resolve().parent
    return _first_existing_path([
        base_dir / name,
        base_dir / "drivers" / name,
    ])

def _make_edge_options():
    opts = EdgeOptions()
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_argument("--autoplay-policy=no-user-gesture-required")
    opts.add_argument("--remote-allow-origins=*")
    opts.add_experimental_option("excludeSwitches", ["enable-automation"])
    opts.add_experimental_option("useAutomationExtension", False)

    edge_path = _first_existing_path([
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "Edge" / "Application" / "msedge.exe",
    ])
    if edge_path:
        opts.binary_location = edge_path
    return opts

def _make_chrome_options():
    opts = ChromeOptions()
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_argument("--autoplay-policy=no-user-gesture-required")
    opts.add_argument("--remote-allow-origins=*")
    opts.add_experimental_option("excludeSwitches", ["enable-automation"])
    return opts

def _make_firefox_options():
    opts = FirefoxOptions()
    opts.set_preference("media.autoplay.default", 0)
    opts.set_preference("media.autoplay.blocking_policy", 0)
    return opts

def build_driver():
    for browser in ["edge", "chrome", "firefox"]:
        try:
            if browser == "edge":
                opts = _make_edge_options()
                local_driver = _local_driver_path("msedgedriver.exe")
                if local_driver:
                    driver = webdriver.Edge(service=EdgeService(local_driver), options=opts)
                else:
                    try:
                        driver = webdriver.Edge(options=opts)
                    except Exception:
                        from webdriver_manager.microsoft import EdgeChromiumDriverManager
                        driver = webdriver.Edge(service=EdgeService(EdgeChromiumDriverManager().install()), options=opts)
            elif browser == "chrome":
                opts = _make_chrome_options()
                local_driver = _local_driver_path("chromedriver.exe")
                if local_driver:
                    driver = webdriver.Chrome(service=ChromeService(local_driver), options=opts)
                else:
                    try:
                        driver = webdriver.Chrome(options=opts)
                    except Exception:
                        from webdriver_manager.chrome import ChromeDriverManager
                        driver = webdriver.Chrome(service=ChromeService(ChromeDriverManager().install()), options=opts)
            else:
                opts = _make_firefox_options()
                local_driver = _local_driver_path("geckodriver.exe")
                if local_driver:
                    driver = webdriver.Firefox(service=FirefoxService(local_driver), options=opts)
                else:
                    try:
                        driver = webdriver.Firefox(options=opts)
                    except Exception:
                        from webdriver_manager.firefox import GeckoDriverManager
                        driver = webdriver.Firefox(service=FirefoxService(GeckoDriverManager().install()), options=opts)
            try:
                driver.execute_script("Object.defineProperty(navigator,'webdriver',{get:()=>undefined})")
            except Exception:
                pass
            browser_name = {"edge": "Edge", "chrome": "Chrome", "firefox": "Firefox"}[browser]
            log(f"浏览器：{browser_name} ✓")
            return driver
        except Exception as e:
            log(f"{browser} 启动失败: {e}")
    raise RuntimeError("Edge / Chrome / Firefox 均无法启动，请至少安装其中一个浏览器。")

def safe_click(driver, el):
    try: el.click()
    except Exception:
        try: driver.execute_script("arguments[0].click();", el)
        except Exception: pass

def mouse_click(driver, el):
    try:
        driver.execute_script("arguments[0].scrollIntoView({block:'center', inline:'center'});", el)
        time.sleep(0.3)
    except Exception:
        pass

    try:
        ActionChains(driver).move_to_element(el).pause(0.15).click().perform()
        return True
    except Exception:
        pass

    try:
        rect = driver.execute_script("""
            var r = arguments[0].getBoundingClientRect();
            return {x: r.left + r.width / 2, y: r.top + r.height / 2};
        """, el)
        driver.execute_script("""
            var x = arguments[0], y = arguments[1];
            var target = document.elementFromPoint(x, y);
            if (!target) return false;
            ['mousemove', 'mousedown', 'mouseup', 'click'].forEach(function(type) {
                target.dispatchEvent(new MouseEvent(type, {
                    bubbles: true,
                    cancelable: true,
                    view: window,
                    clientX: x,
                    clientY: y,
                    buttons: type === 'mouseup' || type === 'click' ? 0 : 1
                }));
            });
            return true;
        """, rect["x"], rect["y"])
        return True
    except Exception:
        safe_click(driver, el)
        return False

def try_play_video(driver):
    if driver.execute_script(CHECK_PLAYING_JS): return True

    HARDWARE_CLICK_JS = """
    try {
        function realClick(el) {
            if(!el) return false;
            ['mousedown', 'mouseup', 'click'].forEach(type => {
                el.dispatchEvent(new MouseEvent(type, {
                    bubbles: true, cancelable: true, view: window, buttons: 1
                }));
            });
            return true;
        }

        var btns = document.querySelectorAll('.vjs-play-control, .bplayer-play-btn, [title="播放"], [aria-label="播放"], .play-btn');
        for(var i=0; i<btns.length; i++) {
            var rect = btns[i].getBoundingClientRect();
            if(rect.width > 0 && rect.width < 100) {
                if (realClick(btns[i])) return true;
            }
        }

        function getV(root) {
            var arr = [];
            if(!root) return arr;
            var els = root.querySelectorAll('*');
            for(var i=0; i<els.length; i++) {
                if(els[i].tagName === 'VIDEO') arr.push(els[i]);
                if(els[i].shadowRoot) arr = arr.concat(getV(els[i].shadowRoot));
            }
            return arr;
        }
        var vs = getV(document);
        var target = null;
        var maxArea = 0;
        for(var i=0; i<vs.length; i++) {
            var area = vs[i].offsetWidth * vs[i].offsetHeight;
            if(area > maxArea) { maxArea = area; target = vs[i]; }
        }
        if(target && maxArea > 100) {
            var rect = target.getBoundingClientRect();
            var cx = rect.left + rect.width / 2;
            var cy = rect.top + rect.height / 2;
            var el = document.elementFromPoint(cx, cy);
            if(el) return realClick(el);
            else return realClick(target);
        }
        return false;
    } catch(e) { return false; }
    """

    try:
        if driver.execute_script(HARDWARE_CLICK_JS):
            time.sleep(2.0)
            if driver.execute_script(CHECK_PLAYING_JS):
                log("视频播放恢复 ▶ (鼠标交互模拟)")
                return True
    except Exception: pass
    return False

def is_video_ended(driver):
    try:
        return driver.execute_script("""
            try {
                function getV(root) {
                    var arr = [];
                    if(!root) return arr;
                    var els = root.querySelectorAll('*');
                    for(var i=0; i<els.length; i++) {
                        if(els[i].tagName === 'VIDEO') arr.push(els[i]);
                        if(els[i].shadowRoot) arr = arr.concat(getV(els[i].shadowRoot));
                    }
                    return arr;
                }
                var vs = getV(document);
                var hasMainVideo = false;
                for(var i=0; i<vs.length; i++) {
                    if(vs[i].offsetWidth > 10) {
                        hasMainVideo = true;
                        if(!vs[i].ended && (vs[i].duration === 0 || Math.abs(vs[i].currentTime - vs[i].duration) > 2)) {
                            return false;
                        }
                    }
                }
                return hasMainVideo;
            } catch(e) { return false; }
        """)
    except Exception: return False

def is_current_chapter_complete(driver):
    try:
        return driver.execute_script("""
            try {
                function visible(el) {
                    var r = el.getBoundingClientRect();
                    return r.width > 20 && r.height > 8;
                }

                function norm(s) {
                    return String(s || '')
                        .replace(/^\\s*\\d+%\\s*/, '')
                        .replace(/^\\s*\\d+[-.、]\\d+\\s*/, '')
                        .replace(/[\\s\\u00a0]+/g, '')
                        .replace(/[▶►▸▹●○◯✓✔√]/g, '');
                }

                function hasPlayingMark(el) {
                    var nodes = [el].concat(Array.prototype.slice.call(el.querySelectorAll('*'), 0, 12));
                    for (var i = 0; i < nodes.length; i++) {
                        var cls = String(nodes[i].className || '').toLowerCase();
                        if (/pause|playing/.test(cls)) return true;
                    }
                    return false;
                }

                var rows = [];
                var items = document.querySelectorAll("li, div[class*='item'], div[class*='chapter'], div[class*='lesson'], div");
                for (var i = 0; i < items.length; i++) {
                    var item = items[i];
                    var txt = (item.innerText || item.textContent || '').trim();
                    if (!visible(item) || txt.indexOf('%') < 0) continue;
                    if ((txt.match(/%/g) || []).length !== 1) continue;
                    var m = txt.match(/(\\d+)%/);
                    if (!m) continue;
                    rows.push({el: item, text: txt, key: norm(txt), pct: parseInt(m[1], 10), top: item.getBoundingClientRect().top});
                }
                if (!rows.length) return false;
                rows.sort(function(a, b) { return a.top - b.top; });

                var firstRowTop = rows[0].top;
                var titles = [];
                var all = document.querySelectorAll('body *');
                for (var j = 0; j < all.length; j++) {
                    var el = all[j];
                    if (!visible(el)) continue;
                    var r = el.getBoundingClientRect();
                    if (r.top >= firstRowTop - 20) continue;
                    var t = (el.innerText || el.textContent || '').trim();
                    if (!t || t.indexOf('%') >= 0 || t.length < 8 || t.length > 160) continue;
                    titles.push(norm(t));
                }
                titles.sort(function(a, b) { return b.length - a.length; });

                for (var pm = 0; pm < rows.length; pm++) {
                    if (hasPlayingMark(rows[pm].el)) return rows[pm].pct >= 100;
                }

                for (var k = 0; k < rows.length; k++) {
                    for (var n = 0; n < Math.min(titles.length, 12); n++) {
                        if (titles[n] && (rows[k].key.indexOf(titles[n]) >= 0 || titles[n].indexOf(rows[k].key) >= 0)) {
                            return rows[k].pct >= 100;
                        }
                    }
                }
                return false;
            } catch(e) { return false; }
        """)
    except Exception: return False

def find_next_chapter(driver):
    try:
        next_item = driver.execute_script("""
            try {
                function visible(el) {
                    var r = el.getBoundingClientRect();
                    return r.width > 80 && r.height > 10;
                }

                function norm(s) {
                    return String(s || '')
                        .replace(/^\\s*\\d+%\\s*/, '')
                        .replace(/^\\s*\\d+[-.、]\\d+\\s*/, '')
                        .replace(/[\\s\\u00a0]+/g, '')
                        .replace(/[▶►▸▹●○◯✓✔√]/g, '');
                }

                function hasPlayingMark(el) {
                    var nodes = [el].concat(Array.prototype.slice.call(el.querySelectorAll('*'), 0, 12));
                    for (var i = 0; i < nodes.length; i++) {
                        var cls = String(nodes[i].className || '').toLowerCase();
                        if (/pause|playing/.test(cls)) return true;
                    }
                    return false;
                }

                var rows = [];
                var items = document.querySelectorAll("li, div[class*='item'], div[class*='chapter'], div[class*='lesson'], div");
                for (var i = 0; i < items.length; i++) {
                    var item = items[i];
                    var txt = (item.innerText || item.textContent || '').trim();
                    if (!visible(item)) continue;
                    if ((txt.match(/%/g) || []).length !== 1) continue;
                    var m = txt.match(/(\\d+)%/);
                    if (!m) continue;
                    rows.push({el: item, text: txt, key: norm(txt), pct: parseInt(m[1], 10), top: item.getBoundingClientRect().top});
                }
                if (!rows.length) return null;
                rows.sort(function(a, b) { return a.top - b.top; });

                var firstRowTop = rows[0].top;
                var titles = [];
                var all = document.querySelectorAll('body *');
                for (var j = 0; j < all.length; j++) {
                    var el = all[j];
                    if (!visible(el)) continue;
                    var r = el.getBoundingClientRect();
                    if (r.top >= firstRowTop - 20) continue;
                    var t = (el.innerText || el.textContent || '').trim();
                    if (!t || t.indexOf('%') >= 0 || t.length < 8 || t.length > 160) continue;
                    titles.push(norm(t));
                }
                titles.sort(function(a, b) { return b.length - a.length; });

                var currentIndex = -1;
                for (var pm = 0; pm < rows.length; pm++) {
                    if (hasPlayingMark(rows[pm].el)) {
                        currentIndex = pm;
                        break;
                    }
                }

                for (var k = 0; currentIndex < 0 && k < rows.length; k++) {
                    for (var n = 0; n < Math.min(titles.length, 12); n++) {
                        if (titles[n] && (rows[k].key.indexOf(titles[n]) >= 0 || titles[n].indexOf(rows[k].key) >= 0)) {
                            currentIndex = k;
                            break;
                        }
                    }
                    if (currentIndex >= 0) break;
                }

                if (currentIndex >= 0) {
                    for (var p = currentIndex + 1; p < rows.length; p++) {
                        if (rows[p].pct < 100) return rows[p].el;
                    }
                    return null;
                }

                for (var q = 0; q < rows.length; q++) {
                    if (rows[q].pct < 100) return rows[q].el;
                }
                return null;
            } catch(e) { return null; }
        """)
        if next_item:
            return next_item
    except Exception: pass

    try:
        items = driver.find_elements(By.CSS_SELECTOR, "li, div[class*='item'], div[class*='chapter']")
        for item in items:
            txt = item.text.strip()
            if "0%" in txt and "100%" not in txt and txt.count("%") == 1 and item.is_displayed():
                clickable = item.find_elements(By.CSS_SELECTOR, "a, span, div")
                if clickable or item.tag_name in ("li", "a"): return item
    except Exception: pass
    try:
        items = driver.find_elements(By.CSS_SELECTOR, "[class*='item'], [class*='chapter'], [class*='lesson']")
        for item in items:
            if item.text.strip().count("%") != 1:
                continue
            progress_els = item.find_elements(By.CSS_SELECTOR, "[class*='percent'], [class*='progress'], span")
            for p in progress_els:
                if p.text.strip() in ("0%", "0"): return item
    except Exception: pass
    return None

def click_next_chapter(driver):
    next_item = find_next_chapter(driver)
    if next_item:
        title = next_item.text.strip().replace('\n', ' ')[:40]
        log(f"切换到下一章节：{title}")
        mouse_click(driver, next_item)
        time.sleep(NEXT_DELAY)
        for _ in range(5):
            if try_play_video(driver): return True
            time.sleep(1)
        return True
    return False

def check_all_complete(driver):
    try:
        prog_el = driver.find_element(By.CSS_SELECTOR, "[class*='total'], [class*='progress'], .progress-text")
        if "100" in prog_el.text: return True
    except Exception: pass
    return find_next_chapter(driver) is None

# ── 弹窗交互处理核心 ──────────────────────
def handle_quiz(driver):
    global tried_answers_history, last_quiz_time, last_quiz_qkey

    # 1. 优先捕获并关闭答错导致的“视频将回退”警告弹窗
    try:
        alerts = driver.find_elements(By.CSS_SELECTOR, "[role='dialog'], .el-message-box, .dialog-wrapper, .bplayer-alert")
        for alert in alerts:
            if alert.is_displayed():
                text = alert.text
                if "回退" in text or "错误" in text or "提示" in text:
                    for btn in alert.find_elements(By.CSS_SELECTOR, "button"):
                        if btn.text.strip() in ("确定", "完成", "关闭", "知道了") and btn.is_displayed():
                            log("检测到平台提示弹窗，已尝试关闭并等待继续...")
                            safe_click(driver, btn)
                            time.sleep(1.5)
                            return True
    except Exception: pass

    # 2. 寻找真正的交互面板
    wraps = driver.find_elements(By.CSS_SELECTOR, ".bplayer-question-wrap, [class*='question-dialog'], [role='dialog']")
    active_wrap = None
    for w in wraps:
        if w.is_displayed() and w.size.get('width', 0) > 100:
            opts = w.find_elements(By.CSS_SELECTOR, "li, .option-item, label.el-radio, label.el-checkbox")
            if len(opts) > 0:
                active_wrap = w
                break
    if not active_wrap: return False

    log("━━ 正在处理交互弹窗 ━━")

    # 获取完整弹窗文字（用于多选题关键词检测）
    full_wrap_text = ""
    try:
        full_wrap_text = active_wrap.text.strip()
    except Exception:
        pass

    question_text = ""
    try:
        header = active_wrap.find_element(By.CSS_SELECTOR, ".bplayer-question-header, [class*='title'], [class*='question'], p")
        question_text = header.text.strip()
    except NoSuchElementException:
        pass
    # 如果 header 没取到，从整体文字中提取第一行作为题干
    if not question_text and full_wrap_text:
        question_text = full_wrap_text.split('\n')[0].strip()

    option_els = active_wrap.find_elements(By.CSS_SELECTOR, "li, .option-item, label.el-radio, label.el-checkbox")
    valid_opts = [el for el in option_els if el.is_displayed() and el.text.strip()]

    if not valid_opts:
        _click_submit_or_done(driver, active_wrap)
        return True

    option_texts = [el.text.strip().replace('\n', ' ') for el in valid_opts]

    # 多选题关键词检测：覆盖【多选题】【多项选择】多选 等所有格式
    detect_text = question_text + full_wrap_text
    is_multi = any(kw in detect_text for kw in ["多选", "多项选择", "多项", "（多选）", "(多选)"])

    # 从 DOM 结构检测 checkbox（兜底）
    has_checkbox = False
    try:
        checkbox_els = active_wrap.find_elements(
            By.CSS_SELECTOR,
            "label.el-checkbox, input[type='checkbox'], [class*='checkbox'], [class*='Checkbox']"
        )
        has_checkbox = len(checkbox_els) > 0
    except Exception:
        pass

    if has_checkbox and not is_multi:
        is_multi = True
        log("DOM检测到checkbox，强制识别为多选题")

    # 防抖：用选项内容生成 q_key（更稳定，不依赖题干文字是否抓到）
    q_key = (question_text or "Q") + "|" + "|".join(option_texts)
    q_key = q_key[:80]
    if q_key == last_quiz_qkey and time.time() - last_quiz_time < 5:
        return False

    log(f"题目类型：{'多选题' if is_multi else '单选题/判断题'} | 题干：{question_text[:40] or '(未识别)'}")

    # 获取所有的答案组合
    all_guesses = generate_all_guesses(option_texts, is_multi)

    if q_key not in tried_answers_history:
        tried_answers_history[q_key] = []

    # 从优先级最高的答案开始，过滤掉已经错过的答案
    current_guess = None
    for g in all_guesses:
        if g not in tried_answers_history[q_key]:
            current_guess = g
            break
            
    # 如果穷尽了所有组合（极端情况防卡死）
    if current_guess is None:
        log("⚠ 所有组合已被穷举！重置该题记忆重新开始...")
        tried_answers_history[q_key] = []
        current_guess = all_guesses[0]

    log(f"提取选项：{' | '.join([t[:15] for t in option_texts])}")
    guess_letters = [chr(65+i) for i in current_guess]
    
    if is_multi:
        if len(tried_answers_history[q_key]) > 1:
            log(f"多选题第{len(tried_answers_history[q_key])}次尝试，新组合：{guess_letters}")
        else:
            log(f"检测到多选题，自动穷举，首次尝试：{guess_letters}")
    elif len(tried_answers_history[q_key]) > 0:
        log(f"根据失败记忆，避开已错选项，本次生成新组合：{guess_letters}")
    else:
        log(f"首次答此题，默认选择：{guess_letters}")

    # 将本次选择加入记忆核心
    tried_answers_history[q_key].append(current_guess)
    last_quiz_qkey = q_key
    last_quiz_time = time.time()

    # 多选题：先取消所有已勾选的选项，再点击目标组合
    if is_multi:
        for idx, el in enumerate(valid_opts):
            try:
                checked = driver.execute_script("""
                    var el = arguments[0];
                    var inp = el.querySelector('input[type=\"checkbox\"]');
                    if (inp) return inp.checked;
                    return el.classList.contains('is-checked') || el.classList.contains('checked');
                """, el)
                if checked:
                    safe_click(driver, el)
                    time.sleep(0.3)
            except Exception:
                pass

    # 物理点击选项
    for idx in current_guess:
        if idx < len(valid_opts):
            safe_click(driver, valid_opts[idx])
            time.sleep(0.5)

    time.sleep(ANSWER_DELAY)
    _click_submit_or_done(driver, active_wrap)
    time.sleep(2)
    return True

def _click_submit_or_done(driver, active_wrap):
    btns = active_wrap.find_elements(By.CSS_SELECTOR, "button, [class*='btn']")
    for btn in btns:
        text = btn.text.strip()
        if text in ("提交", "确定", "确认", "完成", "关闭", "继续播放") and btn.is_displayed():
            log(f"尝试点击弹窗按钮【{text}】")
            safe_click(driver, btn)
            time.sleep(SUBMIT_DELAY)
            return
    for btn in driver.find_elements(By.CSS_SELECTOR, "button"):
        text = btn.text.strip()
        if text in ("提交", "确定", "完成", "关闭") and btn.is_displayed():
            log(f"尝试点击页面兜底按钮【{text}】")
            safe_click(driver, btn)
            time.sleep(SUBMIT_DELAY)
            return

def wait_manual_quiz_done(active_wrap, seconds=600):
    end_time = time.time() + seconds
    while time.time() < end_time:
        try:
            if not active_wrap.is_displayed():
                return True
        except Exception:
            return True
        time.sleep(2)
    return False

def switch_to_learning_tab(driver):
    try:
        if "yxlearning.com/learning/index" in driver.current_url:
            return True
    except Exception:
        pass

    try:
        for handle in reversed(driver.window_handles):
            driver.switch_to.window(handle)
            try:
                if "yxlearning.com/learning/index" in driver.current_url:
                    return True
            except Exception:
                continue
    except Exception:
        return False
    return False

def main():
    print(BANNER)
    try: driver = build_driver()
    except RuntimeError as e: print(f"\n  ❌ {e}"); input("\n  按 Enter 退出..."); return

    driver.maximize_window()
    driver.get(URL)
    print("""
  ┌──────────────────────────────────────────┐
  │  步骤：                                   │
  │  1. 在浏览器中完成登录                    │
  │  2. 点击第一个视频开始播放                │
  │  3. 回到此窗口，按 Enter 开始全自动监控   │
  └──────────────────────────────────────────┘""")
    input("\n  >>> 准备好后按 Enter 开始...\n")
    log("学习辅助模式启动！监控：交互弹窗 + 视频结束章节导航\n")

    answered, chapters, stall_count, last_complete_switch = 0, 0, 0, 0
    try:
        while True:
            try:
                switch_to_learning_tab(driver)

                if handle_quiz(driver):
                    stall_count = 0; continue

                if time.time() - last_complete_switch > 8 and is_current_chapter_complete(driver) and find_next_chapter(driver):
                    log("当前章节已显示 100%，准备切换下一章节...")
                    last_complete_switch = time.time()
                    if click_next_chapter(driver):
                        chapters += 1
                        stall_count = 0
                    continue

                if is_video_ended(driver):
                    log("视频播放完毕，准备切换下一章节...")
                    time.sleep(1.5)
                    if click_next_chapter(driver):
                        chapters += 1
                        log(f"累计切换章节：{chapters} 次\n")
                        stall_count = 0
                    else:
                        if check_all_complete(driver):
                            log("🎉 全部章节已完成！")
                            break
                        log("未找到下一章节，继续等待...")
                    continue

                is_playing = driver.execute_script(CHECK_PLAYING_JS)
                if not is_playing: 
                    stall_count += 1
                else: 
                    stall_count = 0

                if stall_count >= 2:
                    log(f"检测到视频未播放，执行破冰...")
                    try_play_video(driver)
                    stall_count = 0 

                time.sleep(POLL_INTERVAL)

            except WebDriverException as e:
                if "disconnected" in str(e).lower():
                    log("浏览器已关闭，程序退出"); break
                time.sleep(POLL_INTERVAL)
    except KeyboardInterrupt:
        print()
        log(f"已停止。累计切换章节 {chapters} 次。")
    finally:
        try: driver.quit()
        except Exception: pass
    input("\n  按 Enter 退出...")

if __name__ == "__main__":
    main()
