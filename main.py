#!/usr/bin/env python3
"""
fastfetch logo gallery generator
parses builtin.c for real per-logo colors, fetches txt files from GitHub,
outputs a self-contained HTML gallery
"""

import re
import sys
import time
import urllib.request
import urllib.error
import json

BUILTIN_C   = '/tmp/builtin.c'
RAW_BASE    = 'https://raw.githubusercontent.com/fastfetch-cli/fastfetch/master/src/logo/ascii/'
API_URL     = 'https://api.github.com/repos/fastfetch-cli/fastfetch/contents/src/logo/ascii'
OUTPUT      = 'fastfetch_gallery.html'

# ── ANSI named color → CSS ────────────────────────────────────────────────────
ANSI_COLORS = {
    'FF_COLOR_FG_BLACK':         '#1a1a1a',
    'FF_COLOR_FG_RED':           '#cc0000',
    'FF_COLOR_FG_GREEN':         '#4e9a06',
    'FF_COLOR_FG_YELLOW':        '#c4a000',
    'FF_COLOR_FG_BLUE':          '#3465a4',
    'FF_COLOR_FG_MAGENTA':       '#75507b',
    'FF_COLOR_FG_CYAN':          '#06989a',
    'FF_COLOR_FG_WHITE':         '#d3d7cf',
    'FF_COLOR_FG_DEFAULT':       '#d3d7cf',
    'FF_COLOR_FG_LIGHT_BLACK':   '#555753',
    'FF_COLOR_FG_LIGHT_RED':     '#ef2929',
    'FF_COLOR_FG_LIGHT_GREEN':   '#8ae234',
    'FF_COLOR_FG_LIGHT_YELLOW':  '#fce94f',
    'FF_COLOR_FG_LIGHT_BLUE':    '#729fcf',
    'FF_COLOR_FG_LIGHT_MAGENTA': '#ad7fa8',
    'FF_COLOR_FG_LIGHT_CYAN':    '#34e2e2',
    'FF_COLOR_FG_LIGHT_WHITE':   '#eeeeec',
}

# xterm-256 palette (we only need the ones actually used, but let's do the full thing)
def xterm256_to_css(n):
    n = int(n)
    if n < 16:
        basic = [
            '#000000','#800000','#008000','#808000',
            '#000080','#800080','#008080','#c0c0c0',
            '#808080','#ff0000','#00ff00','#ffff00',
            '#0000ff','#ff00ff','#00ffff','#ffffff',
        ]
        return basic[n]
    if n < 232:
        n -= 16
        b = n % 6; n //= 6
        g = n % 6; r = n // 6
        def c(x): return 0 if x == 0 else 55 + x * 40
        return f'#{c(r):02x}{c(g):02x}{c(b):02x}'
    gray = 8 + (n - 232) * 10
    return f'#{gray:02x}{gray:02x}{gray:02x}'

def rgb_macro_to_css(val):
    # val is like "255;95;95"
    parts = val.strip().split(';')
    r, g, b = int(parts[0]), int(parts[1]), int(parts[2])
    return f'#{r:02x}{g:02x}{b:02x}'

def resolve_color(token):
    """Turn a raw C color token into a CSS color string."""
    token = token.strip().rstrip(',').strip()
    # RGB: FF_COLOR_FG_RGB "r;g;b"
    m = re.match(r'FF_COLOR_FG_RGB\s+"([^"]+)"', token)
    if m:
        return rgb_macro_to_css(m.group(1))
    # 256: FF_COLOR_FG_256 "n"
    m = re.match(r'FF_COLOR_FG_256\s+"(\d+)"', token)
    if m:
        return xterm256_to_css(m.group(1))
    # named
    bare = token.split()[0] if token else ''
    return ANSI_COLORS.get(bare, '#d3d7cf')

# ── Parse builtin.c ───────────────────────────────────────────────────────────
def parse_builtin(path):
    """Returns dict: canonical_name (lowercase) → [css_color, ...]"""
    with open(path) as f:
        src = f.read()

    logo_map = {}  # lowercase name → [colors]

    # Each logo block looks like:
    #   {
    #       .names = { "Foo", "foo2" },
    #       ...
    #       .colors = { FF_COLOR_FG_RED, FF_COLOR_FG_WHITE, },
    #   },
    block_re = re.compile(
        r'\{[^{}]*?\.names\s*=\s*\{([^}]+)\}[^{}]*?\.colors\s*=\s*\{([^}]+)\}[^{}]*?\}',
        re.DOTALL
    )

    for m in block_re.finditer(src):
        names_raw  = m.group(1)
        colors_raw = m.group(2)

        # extract quoted names
        names = re.findall(r'"([^"]+)"', names_raw)

        # extract color tokens — split on comma but keep RGB/256 multi-token macros together
        color_tokens = []
        # normalise whitespace
        cr = re.sub(r'\s+', ' ', colors_raw).strip()
        # tokenise: each entry is either
        #   FF_COLOR_FG_256 "N"  /  FF_COLOR_FG_RGB "r;g;b"  /  FF_COLOR_FG_NAME
        for tok in re.finditer(
            r'FF_COLOR_FG_(?:256|RGB)\s+"[^"]*"|FF_COLOR_FG_\w+', cr
        ):
            color_tokens.append(tok.group(0))

        css_colors = [resolve_color(t) for t in color_tokens]
        if not css_colors:
            css_colors = ['#d3d7cf']

        for name in names:
            logo_map[name.lower()] = css_colors
            # also store under original case for display
            logo_map[name] = css_colors  # may overwrite but that's fine

    return logo_map

# ── Fetch helpers ─────────────────────────────────────────────────────────────
def fetch(url, retries=3, delay=1.0):
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(url, timeout=10) as r:
                return r.read().decode('utf-8', errors='replace')
        except Exception as e:
            if attempt < retries - 1:
                time.sleep(delay)
            else:
                raise

def get_logo_list():
    data = json.loads(fetch(API_URL))
    return [f['name'] for f in data if f['name'].endswith('.txt')]

# ── Logo renderer (txt → HTML) ────────────────────────────────────────────────
def render_logo(txt, colors):
    """Replace $N placeholders with <span style="color:..."> tags."""
    out = []
    i = 0
    current = None

    def close():
        nonlocal current
        if current is not None:
            out.append('</span>')
            current = None

    while i < len(txt):
        ch = txt[i]
        if ch == '$' and i + 1 < len(txt):
            nxt = txt[i+1]
            if nxt == '$':           # escaped dollar
                out.append('$')
                i += 2
                continue
            if '1' <= nxt <= '9':
                idx = int(nxt) - 1
                css = colors[idx] if idx < len(colors) else '#d3d7cf'
                if css != current:
                    close()
                    out.append(f'<span style="color:{css}">')
                    current = css
                i += 2
                continue
        if ch == '<':  out.append('&lt;')
        elif ch == '>': out.append('&gt;')
        elif ch == '&': out.append('&amp;')
        else:           out.append(ch)
        i += 1

    close()
    return ''.join(out)

# ── HTML template ─────────────────────────────────────────────────────────────
HTML_HEAD = '''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>fastfetch logo gallery</title>
<style>
:root{--bg:#0d0d0d;--surface:#111;--border:#1a1a1a;--green:#00ff41;--green-dim:#00cc33;--green-glow:rgba(0,255,65,.12);--text:#c0c0c0;--text-dim:#444}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--bg);color:var(--text);font-family:'Courier New',monospace;min-height:100vh}
header{border-bottom:1px solid var(--green-dim);padding:2rem;text-align:center;background:linear-gradient(180deg,#0a1a0a,var(--bg));box-shadow:0 0 60px var(--green-glow)}
header h1{color:var(--green);font-size:2.2rem;letter-spacing:.2em;text-shadow:0 0 20px var(--green)}
header p{color:var(--text-dim);margin-top:.5rem;font-size:.8rem;letter-spacing:.1em}
.controls{padding:1rem 2rem;display:flex;gap:1rem;align-items:center;border-bottom:1px solid var(--border);position:sticky;top:0;background:rgba(13,13,13,.97);backdrop-filter:blur(8px);z-index:100}
.controls input{background:var(--surface);border:1px solid var(--green-dim);color:var(--green);padding:.5rem 1rem;font-family:inherit;font-size:.9rem;outline:none;flex:1;max-width:400px}
.controls input:focus{border-color:var(--green);box-shadow:0 0 10px var(--green-glow)}
.controls input::placeholder{color:var(--text-dim)}
.count{color:var(--text-dim);font-size:.8rem;letter-spacing:.05em;white-space:nowrap}
.count span{color:var(--green)}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:1px;background:var(--border)}
.card{background:var(--bg);padding:1rem;display:flex;flex-direction:column;gap:.6rem;transition:background .15s}
.card:hover{background:#0a150a;box-shadow:inset 0 0 30px var(--green-glow)}
.logo-name{color:var(--green);font-size:.7rem;letter-spacing:.15em;text-transform:uppercase;border-bottom:1px solid var(--border);padding-bottom:.4rem}
.logo-render{font-size:.52rem;line-height:1.15;overflow:hidden;flex:1;white-space:pre;min-height:60px}
.copy-btn{background:transparent;border:1px solid var(--text-dim);color:var(--text-dim);padding:.25rem .6rem;font-family:inherit;font-size:.65rem;cursor:pointer;letter-spacing:.1em;align-self:flex-start;transition:all .15s}
.copy-btn:hover{border-color:var(--green);color:var(--green)}
.copy-btn.copied{border-color:var(--green);color:var(--green);box-shadow:0 0 6px var(--green-glow)}
.hidden{display:none}
footer{text-align:center;padding:2rem;color:var(--text-dim);font-size:.7rem;letter-spacing:.1em;border-top:1px solid var(--border);margin-top:1px}
</style>
</head>
<body>
<header>
  <h1>&gt; fastfetch --list-logos</h1>
  <p>all {total} built-in logos with accurate per-logo colors &nbsp;|&nbsp; copy name → drop in config.jsonc</p>
</header>
<div class="controls">
  <input type="text" id="search" placeholder="search logos..." oninput="filterCards()" autofocus>
  <div class="count">showing <span id="shown">{total}</span> / {total}</div>
</div>
<div class="grid" id="grid">
'''

HTML_TAIL = '''</div>
<footer>source: github.com/fastfetch-cli/fastfetch &nbsp;|&nbsp; colors parsed from builtin.c &nbsp;|&nbsp; drop name into ~/.config/fastfetch/config.jsonc</footer>
<script>
function filterCards(){
  const q=document.getElementById('search').value.toLowerCase();
  const cards=document.querySelectorAll('.card');
  let n=0;
  cards.forEach(c=>{const m=c.dataset.name.includes(q);c.classList.toggle('hidden',!m);if(m)n++;});
  document.getElementById('shown').textContent=n;
}
function copyName(btn,name){
  navigator.clipboard.writeText(name).then(()=>{
    btn.textContent='copied!';btn.classList.add('copied');
    setTimeout(()=>{btn.textContent='copy name';btn.classList.remove('copied');},1500);
  });
}
</script>
</body></html>
'''

CARD_TMPL = '''<div class="card" data-name="{name_lower}">
  <div class="logo-name">{name}</div>
  <pre class="logo-render">{rendered}</pre>
  <button class="copy-btn" onclick="copyName(this,'{name}')">copy name</button>
</div>'''

# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    print('parsing builtin.c for colors...')
    color_map = parse_builtin(BUILTIN_C)
    print(f'  found color data for {len(color_map)//2} logos')

    print('fetching logo file list from GitHub...')
    files = get_logo_list()
    total = len(files)
    print(f'  found {total} logo files')

    cards = []
    BATCH = 10
    done = 0

    print('fetching and rendering logos...')
    for i in range(0, total, BATCH):
        batch = files[i:i+BATCH]
        for fname in batch:
            name = fname.replace('.txt', '')
            try:
                txt = fetch(RAW_BASE + fname)
            except Exception as e:
                print(f'\n  warning: failed to fetch {fname}: {e}')
                txt = '[fetch failed]'

            # look up colors: try exact name, then lowercase
            colors = color_map.get(name) or color_map.get(name.lower()) or ['#d3d7cf']
            rendered = render_logo(txt, colors)

            cards.append(CARD_TMPL.format(
                name_lower=name.lower(),
                name=name,
                rendered=rendered,
            ))
            done += 1
            print(f'\r  {done}/{total} — {name:<40}', end='', flush=True)

        time.sleep(0.05)  # gentle on GitHub

    print(f'\n\nwriting {OUTPUT}...')
    with open(OUTPUT, 'w') as f:
        f.write(HTML_HEAD.replace('{total}', str(total)).replace('{total}', str(total)))
        f.write('\n'.join(cards))
        f.write(HTML_TAIL)

    print(f'done! open with: xdg-open {OUTPUT}')

if __name__ == '__main__':
    main()
