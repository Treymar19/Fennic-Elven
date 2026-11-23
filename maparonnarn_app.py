# Maparonnarn (Fennic Elven / Snow Elf dialect): dictionary + translator.
# Lean rebuild on the Shou-Chiang app scaffold. Vocabulary is read from a Google Doc.
# ── Gradio 5.9.1 gradio_client schema bug workaround (same as app.py) ──
try:
    import gradio_client.utils as _gcu
    _o1 = _gcu._json_schema_to_python_type
    def _s1(schema, defs=None):
        if not isinstance(schema, dict): return "Any"
        if "additionalProperties" in schema and not isinstance(schema["additionalProperties"], dict):
            schema = {k: v for k, v in schema.items() if k != "additionalProperties"}
        return _o1(schema, defs)
    _gcu._json_schema_to_python_type = _s1
    _o2 = _gcu.get_type
    def _s2(schema):
        if not isinstance(schema, dict): return "Any"
        return _o2(schema)
    _gcu.get_type = _s2
except Exception:
    pass

import os, re, time, threading, unicodedata, urllib.request, difflib
import gradio as gr

DOC_ID = "1W-116l4867x-l49Sjh8Wsox5y-SXZ2Zsz_Pw302d_DM"   # doc must be shared "anyone with the link"
DOC_URL = f"https://docs.google.com/document/d/{DOC_ID}/export?format=txt"
HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "maparonnarn_cache.txt")        # last successful live copy
SNAPSHOT = os.path.join(HERE, "maparonnarn_snapshot.txt")  # bundled copy, used if offline
WIKI = os.path.join(HERE, "maparonnarn_wiki_snapshot.txt")  # bundled Common Elven wiki list (static)
TTL = 300                                                  # seconds between automatic re-syncs

# header line in the doc -> how its "A = B" lines are read
SECTIONS = {
    "race names": "rev", "pronouns": "rev",
    "words": "fwd", "married nouns": "fwd", "married verbs": "fwd", "adverbs": "fwd", "adjectives": "fwd",
    "greetings": "phr", "farewells": "phr", "common sayings": "phr", "insults": "phr", "blessings": "phr",
    "family structure": "fam", "counting": "num", "prefix/suffix": "aff",
    "grammar rules": "gram", "grammar in detail": "gram",
}
FE_FIRST = {"bortu"}   # the doc writes this one race line Fennic-first
STOP = {"the", "a", "an", "is", "are", "am", "be", "been", "being", "do", "does", "to", "of"}
PAST = {"was", "were", "did", "had", "yesterday"}
FUT = {"will", "shall", "gonna", "tomorrow"}
ALIAS = {"he": "him", "she": "her", "them": "they", "their": "theirs"}

def norm(s):
    s = unicodedata.normalize("NFKD", s.lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[’‘'`\-]", "", s).strip()

def clean_def(m):
    m = re.sub(r"\(.*?\)", "", m)
    return re.split(r"\bLit\b\.?", m, 1, flags=re.I)[0].strip(" .,;/") or m.strip()

def en_keys(meaning):
    m = re.sub(r"\(.*?\)", "", meaning)
    m = re.split(r"\bLit\b\.?", m, 1, flags=re.I)[0]
    keys = []
    for part in re.split(r"[/,;]", m):
        p = re.sub(r"^(to|a|an|the)\s+", "", part.strip(" .!?'\"").lower())
        if p: keys.append(p)
    return keys

def _adder(W, E):
    def add(form, meaning, label):
        form = form.strip().strip(".!?, ")
        meaning = meaning.strip()
        if not form or not meaning: return
        if " " in form: return
        k = norm(form)
        if not k: return
        e = W.setdefault(k, {"form": form, "defs": [], "sec": label})
        if meaning not in e["defs"]: e["defs"].append(meaning)
        for key in en_keys(meaning):
            lst = E.setdefault(key, [])
            if form not in lst: lst.append(form)
    return add

def parse_wiki(text):
    """Common Elven (Lord of the Craft wiki): '## Section' headers, 'word: meaning' lines."""
    W, E = {}, {}
    add, label = _adder(W, E), "Wiki"
    for raw in text.split("\n"):
        line = raw.strip()
        if line.startswith("## "): label = "Wiki: " + line[3:]; continue
        if ": " in line:
            form, meaning = line.split(": ", 1); add(form, meaning, label)
    return {"WW": W, "WE": E}

def parse(text):
    W, E, P, N, A, G = {}, {}, [], {}, [], []
    sec = None
    add = _adder(W, E)
    for raw in text.split("\n"):
        line = raw.strip()
        key = line.rstrip(":").strip().lower()
        if key in SECTIONS:
            sec = SECTIONS[key]; label = key.title(); continue
        if not line or sec is None: continue
        kind = sec
        if kind == "gram":
            G.append(line); continue
        if kind == "num":
            m = re.match(r"^(\w+)\s*=\s*(\d+)\s*$", line)
            if m: N[int(m.group(2))] = m.group(1)
            continue
        if kind == "fam":
            m = re.match(r"^([^,=]+),\s*(.+)$", line)
            if m: add(m.group(1), m.group(2), label)
            continue
        if kind == "aff":
            if "=" in line:
                a, b = line.split("=", 1); A.append((a.strip(), b.strip()))
            continue
        if "=" in line:
            left, right = (s.strip() for s in line.split("=", 1))
            if not left or not right: continue
            if kind == "rev":
                en, fe = (right, left) if norm(left) in FE_FIRST else (left, right)
                m = re.match(r"^(.*?)\s*\((.*)$", fe)
                note, fe = (m.group(2).rstrip(") "), m.group(1)) if m else ("", fe)
                for f in fe.split("/"):
                    add(f, f"{en} ({note})" if note else en, label)
                continue
            if kind == "phr": P.append((left, right, label))
            add(left, right, label)
            continue
        if kind == "phr":
            m = re.match(r"^(.+?)\s*\((.+)\)\s*$", line)
            if m:
                P.append((m.group(1).strip(), m.group(2).strip(), label)); add(m.group(1), m.group(2), label)
    return {"W": W, "E": E, "P": P, "N": N, "A": A, "G": re.sub(r"\n{3,}", "\n\n", "\n".join(G))}

def fetch_doc(timeout=15):
    req = urllib.request.Request(DOC_URL, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read().decode("utf-8-sig", "replace")
    text = raw.replace("\r\n", "\n").replace("\r", "\n")
    if text.lstrip()[:15].lower().startswith(("<!doctype", "<html")) or text.count("=") < 50:
        raise ValueError("Google returned a web page, not the text (is the doc shared as 'anyone with the link'?)")
    return text

_lock, _DB = threading.Lock(), {}

def _read(p):
    with open(p, encoding="utf-8") as f: return f.read()

def load(force=False):
    global _DB
    with _lock:
        if _DB and not force and time.time() - _DB["t"] < TTL: return _DB
        err, text, src = "", None, ""
        try:
            text, src = fetch_doc(), "live Google Doc"
            try:
                with open(CACHE, "w", encoding="utf-8") as f: f.write(text)
            except OSError:
                pass
        except Exception as e:
            err = f"{type(e).__name__}: {e}"[:160]
            if _DB:
                _DB["t"], _DB["err"] = time.time(), err
                return _DB
            for p, name in ((CACHE, "last saved copy"), (SNAPSHOT, "bundled snapshot")):
                if os.path.exists(p):
                    text, src = _read(p), name; break
            if text is None: text, src = "", "nothing (offline and no snapshot)"
        _DB = parse(text)
        _DB.update(parse_wiki(_read(WIKI)) if os.path.exists(WIKI) else {"WW": {}, "WE": {}})
        _DB.update(src=src, err=err, t=time.time(), stamp=time.strftime("%Y-%m-%d %H:%M"))
        return _DB

def status_md(d):
    s = f"**Source:** {d['src']} · synced {d['stamp']} · **{len(d['W'])}** words · **{len(d['P'])}** phrases · numbers {len(d['N'])}/100 · wiki list: **{len(d['WW'])}** words (bundled)"
    if d.get("err"): s += f"\n\n⚠️ Live sync failed ({d['err']}). Still showing the {d['src']} from {d['stamp']}."
    return s

MODES = ["Snow Elf (doc)", "Common Elven (wiki)", "Mixed"]

def view(d, mode):
    """Words/English index for the chosen dialect. Mixed = Snow Elf first, wiki fills gaps."""
    if mode == MODES[1]: return d["WW"], d["WE"]
    if mode != MODES[2]: return d["W"], d["E"]
    W = {k: dict(e, defs=list(e["defs"])) for k, e in d["W"].items()}
    for k, e in d["WW"].items():
        if k in W: W[k]["defs"] += ["(wiki) " + x for x in e["defs"]]
        else: W[k] = e
    E = {k: list(v) for k, v in d["E"].items()}
    for k, v in d["WE"].items():
        lst = E.setdefault(k, [])
        lst += [f for f in v if f not in lst]
    return W, E

# ── translation ───────────────────────────────────────────────────────────
def to_fennic(text, mode=MODES[0]):
    d, out, notes, tense = load(), [], [], None
    _, E = view(d, mode)
    toks = re.findall(r"[A-Za-z][A-Za-z'’]*", text or "")
    i = 0
    while i < len(toks):
        raw = toks[i]; w = raw.lower().replace("’", "'"); i += 1
        if w in PAST: tense = "past"; continue
        if w in FUT: tense = "future"; continue
        if w == "going" and i < len(toks) and toks[i].lower() == "to": tense = "future"; i += 1; continue
        if w in STOP: continue
        poss = w.endswith("'s")
        if poss: w = w[:-2]
        plural = False
        c = E.get(ALIAS.get(w, w))
        if not c and w in ("i", "my"): c = E.get("me")   # wiki list only has "me"
        if not c and w.endswith("s") and len(w) > 3:
            c = E.get(w[:-1]); plural = bool(c)
        if c:
            f = c[0]
            if len(c) > 1: notes.append(f"- **{raw}**: also {', '.join(c[1:6])}")
        else:
            f = raw   # not in the chosen dictionary: left in English
            if not raw[0].isupper(): notes.append(f"- **{raw}**: not in the dictionary, left in English")
        if plural: f += "’len"
        if poss: f = "au’" + f
        out.append(f)
    if not out: return "Type an English sentence."
    if tense == "past": out[0] = "Ia’" + out[0]
    elif tense == "future": out[0] += "’ia"
    return f"### {' '.join(out)}\n\nWord order is as typed; the doc's order is Subject, Object, Verb.\n\n" + "\n".join(notes)

# ── pick-which-words mode (roleplay: translate only a few words, keep the rest as typed) ──
def lookup_en(raw, E):
    """English word -> (Fennic form or None); handles plural 's, possessive 's and I/my."""
    w = raw.lower().replace("’", "'")
    poss = w.endswith("'s")
    if poss: w = w[:-2]
    c, plural = E.get(ALIAS.get(w, w)), False
    if not c and w.endswith("s") and len(w) > 3:
        c = E.get(w[:-1]); plural = bool(c)
    if not c and w in ("i", "my"): c = E.get("me")
    if not c: return None
    f = c[0] + ("’len" if plural else "")
    return "au’" + f if poss else f

def word_options(text, mode=MODES[0]):
    _, E = view(load(), mode)
    seen, choices = set(), []
    for raw in re.findall(r"[A-Za-z][A-Za-z'’]*", text or ""):
        w, f = raw.lower().replace("’", "'"), lookup_en(raw, E)
        if f and w not in seen:
            seen.add(w); choices.append((f"{raw} → {f}", w))
    return gr.update(choices=choices, value=[])

def partial(text, picks, mode=MODES[0]):
    _, E = view(load(), mode)
    picks = set(picks or [])
    def sub(m):
        raw = m.group(0)
        return (lookup_en(raw, E) or raw) if raw.lower().replace("’", "'") in picks else raw
    return re.sub(r"[A-Za-z][A-Za-z'’]*", sub, text or "")

def gloss_word(W, base, split=True):
    e = W.get(norm(base))
    if e: return clean_def(e["defs"][0]), "; ".join(e["defs"])
    parts = [p for p in re.split(r"[’‘']", base) if p]
    if split and len(parts) > 1:
        es = [W.get(norm(p)) for p in parts]
        if any(es): return " + ".join(clean_def(x["defs"][0]) if x else "?" for x in es), ""
    return None, ""

def to_english(text, mode=MODES[0]):
    d, sent, rows = load(), [], []
    W, _ = view(d, mode)
    for tok in re.findall(r"[^\s,;:!?()\[\]]+", text or ""):
        t = tok.strip(".").replace("‘", "’").replace("'", "’")
        g, allm = gloss_word(W, t, split=False)
        flags, b = [], t
        if g is None:
            if b.lower().startswith("ia’"): flags.append("past"); b = b[3:]
            if b.lower().endswith("’ia"): flags.append("future"); b = b[:-3]
            if b.lower().startswith("au’"): flags.append("possessive"); b = b[3:]
            if b.lower().endswith("’len"): flags.append("plural"); b = b[:-4]
            if b.lower().startswith("tr’"): flags.append("verb"); b = b[3:]
            g, allm = gloss_word(W, b, split=False)
        if g is None: g, allm = gloss_word(W, b)
        if g is None: g = b; allm = "not in the dictionary, left as written"
        if flags: g += f" ({'/'.join(flags)})"
        sent.append(g)
        rows.append(f"| {tok} | {g} | {allm.replace('|', '/')} |")
    if not sent: return "Type a Fennic sentence."
    return f"### {' · '.join(sent)}\n\n| Fennic | Gloss | All meanings |\n|---|---|---|\n" + "\n".join(rows)

# ── dictionary, browse, numbers ───────────────────────────────────────────
def search(q, mode=MODES[0]):
    d, q = load(), (q or "").strip()
    W, E = view(d, mode)
    if not q: return "Type a Fennic or English word."
    k, ql, hits = norm(q), q.lower(), []
    if k in W: hits.append(k)
    for ek, forms in E.items():
        if ek == ql: hits += [norm(f) for f in forms]
    for kk, e in W.items():
        if kk.startswith(k) or any(ql in m.lower() for m in e["defs"]): hits.append(kk)
    hits += difflib.get_close_matches(k, list(W), n=6, cutoff=0.75)
    seen, lines = set(), []
    for kk in hits:
        if kk in seen or kk not in W: continue
        seen.add(kk); e = W[kk]
        lines.append(f"- **{e['form']}**: {'; '.join(e['defs'])} · *{e['sec']}*")
        if len(lines) >= 40: break
    return "\n".join(lines) or f"Nothing found for “{q}”."

def browse(kind, flt, mode=MODES[0]):
    d, f = load(), (flt or "").lower()
    W, _ = view(d, mode)
    if mode == MODES[1] and kind != "Words": return []
    if kind == "Phrases": rows = [list(r) for r in d["P"]]
    elif kind == "Numbers": rows = [[w, str(n), "Counting"] for n, w in sorted(d["N"].items())]
    elif kind == "Affixes": rows = [[a, b, "Prefix/Suffix"] for a, b in d["A"]]
    else: rows = [[e["form"], "; ".join(e["defs"]), e["sec"]] for e in sorted(W.values(), key=lambda e: norm(e["form"]))]
    if f: rows = [r for r in rows if f in " ".join(r).lower()]
    return rows[:1000]

def number(n):
    d = load()
    try: v = int(str(n).strip().replace(",", ""))
    except ValueError: return "Enter a whole number."
    if v < 0 or v >= 10**10: return "Use 0 to 9,999,999,999."
    if len(d["N"]) < 100: return "The doc's 0-99 table is incomplete."
    s, groups = str(v), []
    while s: groups.insert(0, int(s[-2:])); s = s[:-2]
    sfx = ["", "’firr", "’ilk", "’elam", "’karr"]
    return ", ".join(d["N"][g] + sfx[len(groups) - 1 - i] for i, g in enumerate(groups))

def do_sync(kind, flt, mode=MODES[0]):
    d = load(force=True)
    return status_md(d), browse(kind, flt, mode), d["G"]

def refresh(kind, flt, mode=MODES[0]):
    d = load()
    return status_md(d), browse(kind, flt, mode), d["G"]

# ── UI ────────────────────────────────────────────────────────────────────
with gr.Blocks(title="Maparonnarn · Fennic Elven") as demo:
    gr.Markdown("# Maparonnarn · Fennic Elven (Snow Elf dialect)")
    status = gr.Markdown()
    sync_btn = gr.Button("🔄 Sync from Google Doc")
    mode = gr.Radio(MODES, value=MODES[0], label="Dialect (Mixed = Snow Elf first, wiki fills the gaps)")
    with gr.Tabs():
        with gr.Tab("Translate"):
            e_in = gr.Textbox(label="English → Fennic", placeholder="I was cold")
            e_btn = gr.Button("Translate to Fennic")
            e_out = gr.Markdown()
            pick_btn = gr.Button("Or pick which words to translate…")
            pick = gr.CheckboxGroup(label="Tick the words to translate (the rest stay as typed)")
            p_out = gr.Textbox(label="Your sentence", lines=3, interactive=False, show_copy_button=True)
            f_in = gr.Textbox(label="Fennic → English", placeholder="Ia’Ayred ehyubor")
            f_btn = gr.Button("Translate to English")
            f_out = gr.Markdown()
        with gr.Tab("Search"):
            q = gr.Textbox(label="Word (either language)")
            q_btn = gr.Button("Search")
            q_out = gr.Markdown()
        with gr.Tab("Browse"):
            kind = gr.Radio(["Words", "Phrases", "Numbers", "Affixes"], value="Words", label="Show")
            flt = gr.Textbox(label="Filter")
            table = gr.Dataframe(headers=["Fennic", "English", "Section"], interactive=False, wrap=True)
        with gr.Tab("Numbers"):
            n_in = gr.Textbox(label="Number", placeholder="100000000")
            n_btn = gr.Button("Write in Fennic")
            n_out = gr.Textbox(label="Fennic", interactive=False)
        with gr.Tab("Grammar"):
            gram = gr.Textbox(label="Grammar notes from the doc", lines=28, interactive=False)
    outs = [status, table, gram]
    sync_btn.click(do_sync, [kind, flt, mode], outs, api_name=False)
    demo.load(refresh, [kind, flt, mode], outs, api_name=False)
    mode.change(refresh, [kind, flt, mode], outs, api_name=False)
    kind.change(refresh, [kind, flt, mode], outs, api_name=False)
    flt.change(refresh, [kind, flt, mode], outs, api_name=False)
    e_btn.click(to_fennic, [e_in, mode], e_out, api_name=False); e_in.submit(to_fennic, [e_in, mode], e_out, api_name=False)
    pick_btn.click(word_options, [e_in, mode], pick, api_name=False)
    pick.change(partial, [e_in, pick, mode], p_out, api_name=False)
    f_btn.click(to_english, [f_in, mode], f_out, api_name=False); f_in.submit(to_english, [f_in, mode], f_out, api_name=False)
    q_btn.click(search, [q, mode], q_out, api_name=False); q.submit(search, [q, mode], q_out, api_name=False)
    n_btn.click(number, n_in, n_out, api_name=False); n_in.submit(number, n_in, n_out, api_name=False)

if __name__ == "__main__":
    # Render/other hosts set PORT; locally this falls back to 7860 (same as before)
    demo.launch(server_name="0.0.0.0", server_port=int(os.environ.get("PORT", 7860)))
