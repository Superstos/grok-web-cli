#!/usr/bin/env python3
"""
Grok Web CLI — Playwright browser automation for grok.com.
Auth: Firefox sso cookie (auto-extracted). No API key needed.

Setup:
  pip install playwright && playwright install chromium
  python grok.py --login            # One-time: sign in via visible browser
  
Usage:
  python grok.py "prompt"                              # Send a prompt
  python grok.py -o /tmp/out.md "prompt"               # JSON pointer output (agent-native)
  python grok.py -c chat.json "multi-turn prompt"      # Conversation persistence
  python grok.py --brief "concise answer"              # Terse mode
  python grok.py --save-auth                           # Re-extract cookies
  python grok.py --login                               # Interactive browser login

Agent-native output (use -o flag):
  {"ok":true,"f":"/tmp/out.md","s":450,"b":2,"m":"fast","t":22.3}

Model: Grok 4.3 Fast (free tier). Expert/Heavy models require SuperGrok subscription.
"""

import os, sys, json, time, argparse, sqlite3, shutil, re, platform
from pathlib import Path

HOME = Path.home()
DIR = HOME / ".grok-cli"
AUTH_FILE = DIR / "auth.json"
CONV_DIR = DIR / "conversations"
BASE_URL = "https://grok.com"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"

# Model: Grok 4.3 Fast (free tier)
# auto, expert, heavy require SuperGrok subscription
MODEL_FAST = "fast"
MODELS = [MODEL_FAST]
MODEL_LABELS = {MODEL_FAST: "Fast"}

_Q = False
_BRIEF = False


def fail(code, msg):
    print(json.dumps({"ok": False, "err": code, "msg": str(msg)[:500]}, ensure_ascii=False))
    sys.exit(1)


def log(msg):
    if not _Q and sys.stderr.isatty():
        print(f"[grok] {msg}", file=sys.stderr)


def find_firefox_profiles():
    """Find Firefox profile directories across platforms.
    
    Order: FIREFOX_PROFILE_DIR env var → auto-detect OS-specific paths.
    Returns list of Path objects.
    """
    env_dir = os.environ.get("FIREFOX_PROFILE_DIR")
    if env_dir:
        p = Path(env_dir)
        return [p] if p.exists() else []
    
    system = platform.system()
    candidates = []
    
    if system == "Linux":
        # Standard Linux + WSL (Windows Firefox under /mnt/c)
        candidates = [
            Path("/mnt/c/Users"),       # WSL: scan all Windows users
            HOME / ".mozilla" / "firefox",
        ]
    elif system == "Darwin":
        candidates = [
            HOME / "Library" / "Application Support" / "Firefox" / "Profiles",
        ]
    elif system == "Windows":
        candidates = [
            Path(os.environ.get("APPDATA", "")) / "Mozilla" / "Firefox" / "Profiles",
        ]
    
    profiles = []
    for base in candidates:
        if not base.exists():
            continue
        if base.name == "Users":
            # WSL: scan all Windows user directories
            for user_dir in base.iterdir():
                if not user_dir.is_dir() or user_dir.name.startswith('.'):
                    continue
                ff = user_dir / "AppData" / "Roaming" / "Mozilla" / "Firefox" / "Profiles"
                if ff.exists():
                    profiles.extend(ff.iterdir())
        elif base.name == "Profiles":
            profiles.extend(base.iterdir())
        elif base.name == "firefox":
            for child in base.iterdir():
                if child.is_dir() and (child / "cookies.sqlite").exists():
                    profiles.append(child)
        else:
            for child in base.iterdir():
                if child.is_dir():
                    profiles.append(child)
    
    return [p for p in profiles if p.is_dir()]


def extract_firefox_cookies():
    """Extract grok.com cookies from Firefox profiles."""
    best = {}
    for profile in find_firefox_profiles():
        cookies_file = profile / "cookies.sqlite"
        if not cookies_file.exists():
            continue
        try:
            tmp = Path(f"/tmp/grok_ff_{os.getpid()}_{profile.name}.sqlite")
            shutil.copy2(str(cookies_file), str(tmp))
            conn = sqlite3.connect(str(tmp))
            cur = conn.cursor()
            cur.execute(
                "SELECT name,value,host FROM moz_cookies "
                "WHERE host LIKE '%grok.com' "
                "AND name IN ('sso','sso-rw','cf_clearance','__cf_bm')"
            )
            rows = cur.fetchall()
            conn.close()
            tmp.unlink(missing_ok=True)
            
            if len(rows) > len(best):
                best = {}
                for name, value, host in rows:
                    best[name] = value.strip('"')
        except Exception:
            pass
    return best


def load_auth():
    """Load auth from file or extract from browser."""
    if AUTH_FILE.exists():
        try:
            return json.loads(AUTH_FILE.read_text())
        except Exception:
            pass
    
    cookies = extract_firefox_cookies()
    if cookies:
        auth = {"cookies": cookies}
        AUTH_FILE.parent.mkdir(parents=True, exist_ok=True)
        AUTH_FILE.write_text(json.dumps(auth))
        return auth
    
    return {}


def setup_cookies(context, auth):
    """Inject cookies into Playwright context."""
    for name, value in auth.get("cookies", {}).items():
        context.add_cookies([{
            "name": name, "value": value,
            "domain": ".grok.com", "path": "/",
            "httpOnly": name in ("sso", "sso-rw"),
            "secure": True, "sameSite": "None",
        }])


def dismiss_modals(page):
    """Dismiss cookie consent and popup modals."""
    for text in ["Close", "Accept", "Accept All", "Dismiss", "Got it", "Maybe later"]:
        try:
            btns = page.locator(f'button:has-text("{text}")')
            for i in range(btns.count()):
                btn = btns.nth(i)
                if btn.is_visible():
                    btn.click()
                    time.sleep(0.5)
        except Exception:
            pass


def switch_model(page, model):
    """Switch model via the model selector dropdown."""
    if model == MODEL_FAST:
        return
    
    label = MODEL_LABELS.get(model, model)
    
    try:
        model_btn = page.locator(
            'button:has-text("Fast"), button:has-text("Auto"), '
            'button:has-text("Expert"), button:has-text("Heavy")'
        ).first
        if model_btn.count() > 0:
            current = model_btn.inner_text()
            if label in current:
                return
            model_btn.click()
            time.sleep(1.5)
        
        option = page.locator(f'[role="menuitem"]:has-text("{label}")').first
        if option.count() > 0 and option.is_visible():
            option.click()
            time.sleep(2)
            log(f"Model: {label}")
        else:
            option = page.locator(f'[role="menu"] text="{label}"').first
            if option.count() > 0:
                option.click()
                time.sleep(2)
                log(f"Model: {label}")
    except Exception as e:
        log(f"Model switch: {e}")


def load_conv(conv_file):
    """Load conversation state."""
    if conv_file and Path(conv_file).exists():
        try:
            return json.loads(Path(conv_file).read_text())
        except Exception:
            pass
    return {}


def save_conv(conv_file, conv):
    """Save conversation state."""
    if conv_file:
        CONV_DIR.mkdir(parents=True, exist_ok=True)
        Path(conv_file).write_text(json.dumps(conv))


def extract_response(page):
    """Extract the last assistant response from the Grok chat page.
    
    Grok uses 'message-bubble' class divs — one per message.
    The last one is always the assistant's response.
    """
    try:
        js_result = page.evaluate("""() => {
            const bubbles = document.querySelectorAll('[class*="message-bubble"]');
            if (bubbles.length > 0) {
                return bubbles[bubbles.length - 1].textContent.trim();
            }
            return '';
        }""")
        
        text = ""
        if js_result and len(js_result.strip()) > 5:
            text = js_result.strip()
        else:
            body = page.locator("body").inner_text()
            if body:
                text = body
        
        if text:
            text = re.sub(r'^Thought for \d+s\s*', '', text)
            text = re.sub(
                r'\n+(Fast|Auto|Expert|Heavy|Ask Grok anything|'
                r'What do you want to know\?|Search|New Chat|Imagine).*$',
                '', text, flags=re.DOTALL
            )
            return text.strip()
        
        return ""
    except Exception as e:
        log(f"Extraction: {e}")
        return ""


def send_prompt(page, prompt, model=MODEL_FAST):
    """Send a prompt and wait for the response. Returns (text, elapsed_seconds)."""
    dismiss_modals(page)
    
    if _BRIEF:
        prompt = "Be concise. " + prompt
    
    switch_model(page, model)
    
    # Find input element (TipTap/ProseMirror contenteditable div)
    input_el = None
    is_tiptap = False
    
    for sel in ['[contenteditable="true"]', '[role="textbox"]', '.ProseMirror']:
        el = page.locator(sel).first
        if el.count() > 0:
            try:
                el.wait_for(state="visible", timeout=3000)
                input_el = el
                is_tiptap = True
                break
            except Exception:
                pass
    
    if input_el is None:
        for sel in ['textarea:visible', 'textarea:not([aria-hidden])']:
            el = page.locator(sel).first
            if el.count() > 0:
                try:
                    el.wait_for(state="visible", timeout=3000)
                    input_el = el
                    break
                except Exception:
                    pass
    
    if input_el is None:
        fail("no-input", "Cannot find input element on grok.com")
    
    # Type the prompt
    if is_tiptap:
        input_el.click(force=True)
        time.sleep(0.5)
        page.keyboard.press("Control+a")
        page.keyboard.press("Backspace")
        time.sleep(0.2)
        page.keyboard.type(prompt, delay=10)
    else:
        input_el.click()
        time.sleep(0.5)
        input_el.fill(prompt)
    
    time.sleep(0.5)
    
    # Submit: Enter, then fallback to button click
    input_el.press("Enter")
    time.sleep(1)
    
    for btn_text in ["Submit", "Send", "→"]:
        btn = page.locator(f'button:has-text("{btn_text}")').first
        if btn.count() > 0:
            try:
                if btn.is_visible() and btn.is_enabled():
                    btn.click()
                    time.sleep(1)
                    break
            except Exception:
                pass
    
    # Wait for response completion
    log("Waiting for response...")
    deadline = time.time() + 120
    started = time.time()
    
    while time.time() < deadline:
        stop_btns = page.locator('button:has-text("Stop"), button[aria-label="Stop"]')
        copy_btns = page.locator('button:has-text("Copy"), button[aria-label="Copy"]')
        
        stop_visible = copy_visible = False
        try:
            if stop_btns.count() > 0:
                stop_visible = stop_btns.first.is_visible()
        except Exception:
            pass
        try:
            if copy_btns.count() > 0:
                copy_visible = copy_btns.first.is_visible()
        except Exception:
            pass
        
        if not stop_visible and copy_visible:
            time.sleep(2)
            break
        
        if not stop_visible and time.time() - started > 10:
            time.sleep(2)
            try:
                if stop_btns.count() == 0 or not stop_btns.first.is_visible():
                    break
            except Exception:
                break
        
        time.sleep(2)
    else:
        log("Timeout — extracting partial response...")
    
    elapsed = time.time() - started
    time.sleep(1)
    return extract_response(page), elapsed


def run_browser_login():
    """Open visible browser for one-time login. Saves cookies to auth.json."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        fail("no-playwright", "Playwright not installed. Run: pip install playwright && playwright install chromium")
    
    log("Opening browser for login. Sign in to Grok, then close the browser.")
    
    profile_dir = DIR / "profile"
    profile_dir.mkdir(parents=True, exist_ok=True)
    
    with sync_playwright() as pw:
        context = pw.chromium.launch_persistent_context(
            str(profile_dir),
            headless=False,
            viewport={"width": 1280, "height": 800},
            args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
        )
        page = context.pages[0] if context.pages else context.new_page()
        page.goto(BASE_URL, wait_until="domcontentloaded", timeout=30000)
        time.sleep(3)
        
        log("Waiting for login... (timeout: 10 minutes)")
        
        for _ in range(600):
            signin = page.locator('button:has-text("Sign in")').count()
            if signin == 0:
                cookies = context.cookies()
                auth = {"cookies": {}}
                for c in cookies:
                    if 'grok.com' in c.get('domain', ''):
                        auth["cookies"][c['name']] = c['value']
                
                AUTH_FILE.parent.mkdir(parents=True, exist_ok=True)
                AUTH_FILE.write_text(json.dumps(auth))
                log("Login successful! Auth saved to ~/.grok-cli/auth.json")
                context.close()
                return True
            time.sleep(1)
        
        context.close()
        fail("login-timeout", "Login timed out after 10 minutes.")


def grok_chat(prompt, model=MODEL_FAST, conv_file=None, fresh=False):
    """Main chat function. Returns (response_text, elapsed_seconds)."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        fail("no-playwright", "Playwright not installed. Run: pip install playwright && playwright install chromium")
    
    auth = load_auth()
    if not auth or not auth.get("cookies", {}).get("sso"):
        fail("no-auth", "Not logged in. Run: python grok.py --login")
    
    conv = {} if fresh else load_conv(conv_file)
    
    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
        )
        context = browser.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent=UA,
        )
        setup_cookies(context, auth)
        page = context.new_page()
        
        log("Loading grok.com...")
        
        if conv.get("url") and not fresh:
            page.goto(conv["url"], wait_until="domcontentloaded", timeout=30000)
        else:
            page.goto(BASE_URL, wait_until="domcontentloaded", timeout=30000)
        
        time.sleep(8)
        dismiss_modals(page)
        time.sleep(2)
        
        # Verify authentication
        deadline = time.time() + 15
        logged_in = False
        while time.time() < deadline:
            signin = page.locator('button:has-text("Sign in")').count()
            signup = page.locator('button:has-text("Sign up")').count()
            if signin == 0 and signup == 0:
                logged_in = True
                break
            time.sleep(2)
        
        if not logged_in:
            page.goto(BASE_URL, wait_until="domcontentloaded", timeout=30000)
            time.sleep(8)
            dismiss_modals(page)
            time.sleep(2)
            signin = page.locator('button:has-text("Sign in")').count()
            signup = page.locator('button:has-text("Sign up")').count()
            if signin > 0 or signup > 0:
                browser.close()
                fail("auth-expired", "Session expired. Run: python grok.py --login")
        
        dismiss_modals(page)
        
        log(f"Sending (model={model})...")
        response_text, elapsed = send_prompt(page, prompt, model)
        
        conv["url"] = page.url
        browser.close()
    
    save_conv(conv_file, conv)
    return response_text, elapsed


def main():
    global _Q, _BRIEF
    
    parser = argparse.ArgumentParser(
        description="Grok Web CLI — browser-cookie auth for grok.com"
    )
    parser.add_argument("prompt", nargs="?", help="Prompt to send")
    parser.add_argument("-m", "--model", default=MODEL_FAST, choices=MODELS,
                        help=f"Model (default: {MODEL_FAST})")
    parser.add_argument("-c", "--conv", help="Conversation state file for multi-turn")
    parser.add_argument("--new", action="store_true", help="Start fresh conversation")
    parser.add_argument("-o", "--output", help="Write response to FILE (stdout gets JSON pointer)")
    parser.add_argument("--json", action="store_true", help="Full JSON output on stdout")
    parser.add_argument("--brief", action="store_true", help="Prepend 'Be concise.' for terse responses")
    parser.add_argument("-l", "--login", action="store_true", help="Open visible browser for interactive login")
    parser.add_argument("-q", "--quiet", action="store_true", help="Suppress stderr progress messages")
    parser.add_argument("--save-auth", action="store_true", help="Re-extract cookies from Firefox profiles")
    
    args = parser.parse_args()
    _Q = args.quiet
    _BRIEF = args.brief
    
    if args.login:
        run_browser_login()
        print(json.dumps({"ok": True, "msg": "Login successful"}))
        return
    
    if args.save_auth:
        cookies = extract_firefox_cookies()
        if cookies:
            auth = {"cookies": cookies}
            AUTH_FILE.parent.mkdir(parents=True, exist_ok=True)
            AUTH_FILE.write_text(json.dumps(auth))
            print(json.dumps({"ok": True, "msg": f"Saved {len(cookies)} cookies"}))
        else:
            fail("no-auth", "No Grok cookies found. Sign in at grok.com in Firefox first, then retry.")
        return
    
    if not args.prompt:
        parser.print_help()
        sys.exit(1)
    
    try:
        response_text, elapsed = grok_chat(
            args.prompt, model=args.model,
            conv_file=args.conv, fresh=args.new,
        )
    except SystemExit:
        raise
    except Exception as e:
        fail("error", str(e))
    
    code_blocks = response_text.count("```") // 2
    
    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(response_text)
        size = out_path.stat().st_size
        print(json.dumps({
            "ok": True, "f": str(out_path), "s": size,
            "b": code_blocks, "m": args.model, "t": round(elapsed, 1),
        }, ensure_ascii=False))
    elif args.json:
        print(json.dumps({
            "ok": True, "text": response_text, "s": len(response_text),
            "b": code_blocks, "m": args.model, "t": round(elapsed, 1),
        }, ensure_ascii=False))
    else:
        print(response_text)


if __name__ == "__main__":
    main()
