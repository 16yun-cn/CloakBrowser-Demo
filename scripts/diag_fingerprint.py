#!/usr/bin/env python3
"""
CAPTCHA fingerprint diagnostic — tests AFTER chat submit triggers CAPTCHA.

Usage: python3 scripts/diag_fingerprint.py noise
       python3 scripts/diag_fingerprint.py intercept
       python3 scripts/diag_fingerprint.py windows
"""

import json, os, sys, time, urllib.request as _urlreq
from pathlib import Path

try:
    import tomllib
except ImportError:
    import tomli as tomllib

sys.path.insert(0, "CloakBrowser")
from cloakbrowser import launch_persistent_context

CONFIG_PATH = Path("config.toml")
DIAG_DIR = Path(".runtime/diag")
DIAG_DIR.mkdir(parents=True, exist_ok=True)
USE_PROXY = os.environ.get("DIAG_USE_PROXY") == "1"

def log(msg): print(f"  {msg}", flush=True)
def section(t): print(f"\n{'='*60}\n  {t}\n{'='*60}")

# ── Browser ──────────────────────────────────────────────

def _launch_kwargs():
    cfg = tomllib.loads(CONFIG_PATH.read_text())
    fp = cfg["fingerprint"]
    kwargs = {"headless": False, "humanize": True, "stealth_args": False}
    if USE_PROXY:
        pc = cfg.get("proxy", {})
        s = pc["server"]; u = pc.get("username",""); p = pc.get("password","")
        kwargs["proxy"] = f"{s.split('://')[0]}://{u}:{p}@{s.split('://',1)[1]}" if u else s
    sw, sh = fp.get("screen_width"), fp.get("screen_height")
    if sw and sh: kwargs["viewport"] = {"width": int(sw), "height": int(sh)}
    return kwargs

def _build_args(overrides=None):
    fp = dict(tomllib.loads(CONFIG_PATH.read_text())["fingerprint"])
    if overrides: fp.update(overrides)
    args = [
        f"--fingerprint={fp['seed']}", f"--fingerprint-platform={fp['platform']}",
        f"--fingerprint-brand={fp['brand']}", f"--fingerprint-brand-version={fp['brand_version']}",
        f"--fingerprint-platform-version={fp['platform_version']}",
        f"--fingerprint-gpu-vendor={fp['gpu_vendor']}", f"--fingerprint-gpu-renderer={fp['gpu_renderer']}",
        f"--fingerprint-hardware-concurrency={fp['hardware_concurrency']}",
        f"--fingerprint-device-memory={fp['device_memory']}",
        f"--fingerprint-screen-width={fp['screen_width']}", f"--fingerprint-screen-height={fp['screen_height']}",
        f"--fingerprint-timezone={fp['timezone']}", f"--fingerprint-locale={fp['locale']}",
        f"--fingerprint-storage-quota={fp['storage_quota_mb']}", f"--fingerprint-webrtc-ip={fp['webrtc_ip_mode']}",
    ]
    if str(fp.get("noise","false")).lower() in ("false","0","no","off"):
        args.append("--fingerprint-noise=false")
    return args

def launch(extra_args=None, profile="diag"):
    args = _build_args(); 
    if extra_args: args.extend(extra_args)
    kw = _launch_kwargs(); kw["args"] = args
    ctx = launch_persistent_context(str(DIAG_DIR/profile), **kw)
    return ctx, ctx.new_page()

# ── CAPTCHA bypass ───────────────────────────────────────

BYPASS_DOMAINS = [
    "zijieapi.com", "bytedance.com",
    "captcha.gtimg.com", "t.captcha.qq.com", "captcha.qq.com",
    "captcha.baidu.com", "api.geetest.com", "static.geetest.com",
    "gcaptcha4.geetest.com", "captcha1.guard.qcloud.com",
]

def install_bypass(page):
    def _fetch(route):
        try:
            rh = {k:v for k,v in route.request.headers.items()}
            rh.pop("proxy-authorization",None); rh.pop("proxy-connection",None)
            req = _urlreq.Request(route.request.url, headers=rh)
            with _urlreq.urlopen(req, timeout=15) as r:
                body = r.read(); hd = dict(r.headers)
                hd.pop("transfer-encoding",None); hd.pop("content-encoding",None)
                route.fulfill(status=r.status, headers=hd, body=body)
        except: 
            try: route.continue_()
            except: pass
    for d in BYPASS_DOMAINS:
        try: page.route(f"**/*{d}**", _fetch)
        except: pass
    log(f"Bypass installed for {len(BYPASS_DOMAINS)} domains")

# ── Chat interaction ─────────────────────────────────────

INPUT_SELS = ["textarea[placeholder*='豆包']","textarea[placeholder*='发送']",
              "[role='textbox'][contenteditable='true']","[contenteditable='true']","textarea"]
SUBMIT_SELS = ["button:has-text('发送')","button:has-text('发送消息')","button[aria-label*='发送']"]

def find_visible(page, sels, timeout=5000):
    dl = time.time()+timeout/1000
    while time.time()<dl:
        for s in sels:
            try:
                l=page.locator(s).first
                if l.count()>0 and l.is_visible(): return l
            except: continue
        time.sleep(0.3)
    return None

def fill_input(page, loc, text):
    loc.scroll_into_view_if_needed(); loc.click(); time.sleep(0.3)
    tag=(loc.evaluate("n=>n.tagName")or"").lower()
    if tag in("textarea","input"): loc.fill(text)
    else: loc.evaluate("(el,t)=>{el.focus();el.textContent=t;el.dispatchEvent(new InputEvent('input',{bubbles:true,inputType:'insertText',data:t}))}",text)

def click_submit(page, inp):
    for s in SUBMIT_SELS:
        try:
            b=page.locator(s).first
            if b.count()>0 and b.is_visible(): b.click(); log(f"Submit: {s}"); return
        except: continue
    inp.press("Enter"); log("Submit: Enter key")

def trigger(page, prompt="你好，请介绍一下你自己"):
    log(f"Typing: {prompt}")
    el=find_visible(page,INPUT_SELS,10000)
    if not el: log("WARN: no input found"); return False
    fill_input(page,el,prompt); time.sleep(0.5)
    log("Clicking submit..."); click_submit(page,el)
    return True

# ── DOM check ────────────────────────────────────────────

def check_dom(page):
    return page.evaluate("""()=>{
        const r={found:false,details:[]};
        for(const s of ['.tcaptcha-transform-container','#tcaptcha_transform_dy','.tcaptcha-transform','[class*="captcha"]','[id*="captcha"]','[class*="verify"]','[class*="shield"]']){
            for(const e of document.querySelectorAll(s)){
                const rc=e.getBoundingClientRect();
                if(rc.width>0&&rc.height>0){
                    const imgs=[];
                    for(const i of e.querySelectorAll('img')) imgs.push({nw:i.naturalWidth,nh:i.naturalHeight,complete:i.complete,src:i.src.substring(0,70)});
                    r.found=true; r.details.push({sel:s,sz:{w:rc.width,h:rc.height},ic:imgs.length,imgs:imgs.slice(0,12),err:(e.textContent||'').includes('失败'),txt:(e.textContent||'').trim().substring(0,150)});
                }
            }
        }
        const bt=document.body.textContent||'';
        if(bt.includes('5202'))r.code5202=true;
        return r;
    }""")

def signals(page):
    return page.evaluate("""()=>({wd:navigator.webdriver,ua:navigator.userAgent,pl:navigator.platform,hc:navigator.hardwareConcurrency,dm:navigator.deviceMemory,lg:navigator.languages,plugs:Array.from(navigator.plugins).map(p=>p.name),wc:typeof window.chrome,wcr:!!(window.chrome&&window.chrome.runtime),sc:{w:screen.width,h:screen.height},in:{w:window.innerWidth,h:window.innerHeight},tz:Intl.DateTimeFormat().resolvedOptions().timeZone})""")

def canvas_hash(page):
    return page.evaluate("""()=>{const c=document.createElement('canvas');c.width=280;c.height=60;const x=c.getContext('2d');x.textBaseline='top';x.font='14px Arial';x.fillStyle='#f60';x.fillRect(125,1,62,20);x.fillStyle='#069';x.fillText('Test!',2,15);const d=c.toDataURL();let h=0;for(let i=0;i<d.length;i++){h=((h<<5)-h)+d.charCodeAt(i);h|=0;}return{len:d.length,hash:h}}""")

# ── Monitor ──────────────────────────────────────────────

def monitor(page, label, sec=25, ss_prefix="diag"):
    for i in range(sec):
        c=check_dom(page)
        if c["found"]:
            d=c["details"][0]; im=d.get("imgs",[])
            ld=sum(1 for x in im if x.get("nw",0)>20)
            st="❌ERR" if d.get("err") else ("✅LOADED" if ld>=9 else f"⏳{ld}/{len(im)}")
            log(f"t={i+1:2d}s: CAPTCHA imgs={len(im)} loaded={ld} {st}")
            if d.get("err"):
                log(f"  TEXT: {d.get('txt','')[:120]}")
                page.screenshot(path=str(DIAG_DIR/f"{ss_prefix}-err.png"),full_page=False)
            if ld>=9 and not d.get("err"):
                log("  ✅ All loaded!")
                page.screenshot(path=str(DIAG_DIR/f"{ss_prefix}-ok.png"),full_page=False)
                return "loaded"
        else: log(f"t={i+1:2d}s: no CAPTCHA")
        time.sleep(1)
    page.screenshot(path=str(DIAG_DIR/f"{ss_prefix}-final.png"),full_page=False)
    c=check_dom(page)
    return "timeout" if not c["found"] else ("error" if c["details"][0].get("err") else "unknown")

# ═══════════════════════════════════════════════════════════
#  TESTS
# ═══════════════════════════════════════════════════════════

def t_noise():
    section("TEST: noise=false (current config)")
    ctx,page=launch(); 
    try:
        install_bypass(page)
        page.goto("https://www.doubao.com",wait_until="domcontentloaded")
        try: page.wait_for_load_state("load",timeout=15000)
        except: pass; time.sleep(2)
        s=signals(page); ch=canvas_hash(page)
        log(f"webdriver={s['wd']} canvasHash={ch['hash']} platform={s['pl']}")
        logs=[]; page.on("console",lambda m:logs.append(f"[{m.type}]{m.text[:200]}"))
        trigger(page)
        r=monitor(page,"noise-false",25,"noise-false")
        errs=[m for m in logs if any(k in m.lower() for k in["captcha","verify","fingerprint","fail","error","5202"])]
        if errs:
            print(f"\n  Console ({len(errs)}):")
            for m in errs[-15:]: print(f"  {m[:200]}")
        log(f"Result: {r}")
    finally:
        try: page.remove_listener("console",lambda m:None)
        except: pass
        ctx.close()

def t_noise_true():
    section("TEST: noise=true (inject noise)")
    ctx,page=launch(extra_args=["--fingerprint-noise=true"])
    try:
        install_bypass(page)
        page.goto("https://www.doubao.com",wait_until="domcontentloaded")
        try: page.wait_for_load_state("load",timeout=15000)
        except: pass; time.sleep(2)
        s=signals(page); ch=canvas_hash(page)
        log(f"webdriver={s['wd']} canvasHash={ch['hash']} platform={s['pl']}")
        trigger(page)
        r=monitor(page,"noise-true",25,"noise-true")
        log(f"Result: {r}")
    finally: ctx.close()

def t_windows():
    section("TEST: platform=windows + noise=false")
    ctx,page=launch(extra_args=["--fingerprint-platform=windows","--fingerprint-noise=false"])
    try:
        install_bypass(page)
        page.goto("https://www.doubao.com",wait_until="domcontentloaded")
        try: page.wait_for_load_state("load",timeout=15000)
        except: pass; time.sleep(2)
        s=signals(page); log(f"platform={s['pl']} webdriver={s['wd']}")
        trigger(page)
        r=monitor(page,"platform-win",25,"platform-win")
        log(f"Result: {r}")
    finally: ctx.close()

def t_stock():
    section("TEST: Stock Playwright Chromium (no stealth patches)")
    try:
        from playwright.sync_api import sync_playwright
        pw=sync_playwright().start()
        ctx=pw.chromium.launch_persistent_context(str(DIAG_DIR/"stock"),headless=False,viewport={"width":1440,"height":900})
        page=ctx.new_page()
        page.goto("https://www.doubao.com",wait_until="domcontentloaded")
        try: page.wait_for_load_state("load",timeout=15000)
        except: pass; time.sleep(2)
        wd=page.evaluate("()=>navigator.webdriver"); log(f"webdriver={wd}")
        trigger(page)
        r=monitor(page,"stock",25,"stock")
        log(f"Result: {r}")
    except ImportError: log("SKIP: playwright not installed")
    finally: 
        try: ctx.close(); pw.stop()
        except: pass

def t_intercept():
    section("TEST: Intercept fingerprint API calls")
    ctx,page=launch(extra_args=["--fingerprint-noise=false"])
    try:
        install_bypass(page)
        page.add_init_script("""
            (()=>{
                const L=(...a)=>{console.warn('[FP-API]',...a)};
                const oT=HTMLCanvasElement.prototype.toDataURL;
                HTMLCanvasElement.prototype.toDataURL=function(...a){const r=oT.apply(this,a);L('canvas.toDataURL',this.width+'x'+this.height,'len='+r.length);return r};
                const oG=HTMLCanvasElement.prototype.getContext;
                HTMLCanvasElement.prototype.getContext=function(t,...a){L('canvas.getContext',t);return oG.apply(this,[t,...a])};
                try{const c=document.createElement('canvas');const g=c.getContext('webgl')||c.getContext('experimental-webgl');
                if(g){const oP=WebGLRenderingContext.prototype.getParameter;const nm={37445:'VENDOR',37446:'RENDERER',7937:'VENDOR2',7938:'RENDERER2'};
                WebGLRenderingContext.prototype.getParameter=function(p){const r=oP.call(this,p);if(nm[p])L('webgl.getParameter',nm[p],String(r).substring(0,80));return r}}}catch(e){L('webgl-patch-err',e.message)}
                const OAC=window.AudioContext||window.webkitAudioContext;
                if(OAC){const nm=window.AudioContext?'AudioContext':'webkitAudioContext';window[nm]=function(...a){const i=new OAC(...a);L('new AudioContext','sr='+i.sampleRate);return i};window[nm].prototype=OAC.prototype}
            })()
        """)
        apis=[]
        def on_c(m):
            if"[FP-API]"in m.text: apis.append(m.text)
            elif m.type=="error": apis.append(f"[ERR]{m.text[:200]}")
        page.on("console",on_c)
        page.goto("https://www.doubao.com",wait_until="domcontentloaded")
        try: page.wait_for_load_state("load",timeout=15000)
        except: pass; time.sleep(2)
        s=signals(page); ch=canvas_hash(page)
        log(f"webdriver={s['wd']} canvasHash={ch['hash']}")
        trigger(page)
        for i in range(25):
            c=check_dom(page)
            if c["found"]: d=c["details"][0]; im=d.get("imgs",[]); ld=sum(1 for x in im if x.get("nw",0)>20); log(f"t={i+1}s: imgs={len(im)} loaded={ld} err={d.get('err')}")
            time.sleep(1)
        print(f"\n  Intercepted APIs ({len(apis)}):")
        for m in apis[-50:]: print(f"  {m[:250]}")
        page.screenshot(path=str(DIAG_DIR/"intercept-final.png"),full_page=False)
    finally:
        try: page.remove_listener("console",on_c)
        except: pass
        ctx.close()

# ═══════════════════════════════════════════════════════════

STEPS={"noise":t_noise,"noise-true":t_noise_true,"windows":t_windows,"stock":t_stock,"intercept":t_intercept}

if __name__=="__main__":
    cmd=sys.argv[1]if len(sys.argv)>1 else"all"
    if cmd=="all":
        for n,f in STEPS.items():
            try: f()
            except Exception as e: log(f"❌ {n}: {e}")
    elif cmd in STEPS: STEPS[cmd]()
    else: print(f"Unknown: {cmd}. Options: {', '.join(STEPS.keys())}")
