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
SHEET_ID = "1VRkqLhSXYRvWEFtWNwlprYyNJtJmznOuwXMPXMeaVDM"   # Vel'luah sheet, shared "anyone with the link"
DARK_TABS = [("Special Words", "1721718391", "words"), ("Dictionary", "0", "dict"), ("Grammar", "1887383092", "grammar")]   # (title, gid, layout); add the Grammar tab's gid here if wanted
DARK_SNAPSHOT = os.path.join(HERE, "maparonnarn_dark_snapshot.csv")   # bundled copy of the Special Words tab
DARK_SNAPSHOTS = {"1721718391": DARK_SNAPSHOT, "1887383092": os.path.join(HERE, "maparonnarn_dark_grammar_snapshot.csv")}   # the Dictionary tab has none: it is live only
MY_FILE = os.path.join(HERE, "my_words.txt")   # your own words: "Fennic = English", one per line
WIKI_FILE = os.path.join(HERE, "maparonnarn_wiki_snapshot.txt")  # bundled Common Elven wiki list (static)
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
    if " — " in m: return m.split(" — ")[0].strip()   # dark elf entries: "direct translation — explanation"
    m = re.sub(r"\(.*?\)", "", m)
    m = re.split(r"\bLit\b\.?", m, 1, flags=re.I)[0].strip(" .,;/") or m.strip()
    return re.split(r"[.;:/] ", m, 1)[0] if len(m) > 60 else m

def en_keys(meaning):
    m = re.sub(r"\(.*?\)", "", meaning)
    m = re.split(r"\bLit\b\.?", m, 1, flags=re.I)[0]
    keys = []
    for part in re.split(r"[/,;]", m):
        p = re.sub(r"^(to|a|an|the)\s+", "", part.strip(" .!?'\"").lower())
        if p: keys.append(p)
    return keys

def _adder(W, E):
    def add(form, meaning, label, index=None):
        form = form.strip().strip(".!?, ")
        meaning = meaning.strip()
        if not form or not meaning: return
        if " " in form: return
        k = norm(form)
        if not k: return
        e = W.setdefault(k, {"form": form, "defs": [], "sec": label})
        if meaning not in e["defs"]: e["defs"].append(meaning)
        for key in (en_keys(meaning) if index is None else index):
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

NUMS = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten"]

DICT_CATS = ["Prefixes", "Suffixes", "Verbs", "Nouns", "Pronouns", "Articles", "Question Words", "Conjunctions", "Prepositions", "Adjectives", "Adverbs"]

def _parse_dict_tab(rows, add, P, A, label):
    """Dictionary tab: a (Common | Vel'luah) column pair per word type, spacer columns between."""
    if not rows: return
    head = rows[0]
    starts = [i for i in range(len(head) - 1) if head[i].strip().lower() == "common" and "vel" in head[i + 1].lower()]
    for c, i in enumerate(starts):
        cat = DICT_CATS[c] if c < len(DICT_CATS) else f"Column {i + 1}"
        for row in rows[1:]:
            en = row[i].strip() if i < len(row) else ""
            ve = row[i + 1].strip() if i + 1 < len(row) else ""
            if not en or not ve: continue
            if cat in ("Prefixes", "Suffixes") or ve.startswith("-") or ve.endswith("-"):
                A.append((ve, en)); continue
            if " " in ve: P.append((ve, en, f"{label} / {cat}"))
            else: add(ve, en, f"{label} / {cat}", index=en_keys(re.sub(r"\[.*?\]", "", en)))

def parse_dark(sources):
    """Vel'luah sheet tabs as CSV: A word, B meaning, C direct translation, F/G numeral or suffix."""
    import csv, io
    W, E, P, N, A, DL, DG = {}, {}, [], {}, [], {}, []
    add = _adder(W, E)
    for title, kind, text in sources:
        label = "Dark Elf: " + title
        if kind == "grammar":
            DG += [r[0].strip() for r in csv.reader(io.StringIO(text)) if r and r[0].strip()]; continue
        if kind == "dict":
            _parse_dict_tab(list(csv.reader(io.StringIO(text))), add, P, A, label); continue
        for i, row in enumerate(csv.reader(io.StringIO(text))):
            if i == 0: continue
            form, mean, direct, num, nw = ((row + [""] * 8)[j].strip() for j in (0, 1, 2, 5, 6))
            lt, gl = (row + [""] * 8)[3].strip(), (row + [""] * 8)[4].strip()
            if lt and gl: DL[lt[0].lower()] = gl   # letter table for the script tab
            if num and nw:
                if num.isdigit():
                    N[int(num)] = nw
                    if int(num) < len(NUMS): add(nw, f"number {num}", "Dark Elf: numerals", index=[NUMS[int(num)]])
                else: A.append((nw, f"suffix for {num}"))
            if not form: continue
            ok = bool(direct) and direct.upper() != "N/A"
            meaning = f"{direct} — {mean}" if ok else mean
            keys = en_keys(direct) if ok and not re.search(r"insult|derogatory", mean, re.I) else []
            for f in re.split(r"\s*/\s*|\s*\|\s*", form):
                g = re.search(r"\((fem|masc)\)", f)
                f = re.sub(r"\s*\((fem|masc)\)", "", f).strip()
                m = f"({g.group(1)}) {meaning}" if g else meaning
                if not f: continue
                if " " in f: P.append((f, m, label))
                else: add(f, m, label, index=keys)
    return {"DW": W, "DE": E, "DP": P, "DN": N, "DA": A, "DL": DL, "DG": "\n\n".join(DG)}

def load_mine():
    W, E = {}, {}
    add = _adder(W, E)
    for raw in (_read(MY_FILE) if os.path.exists(MY_FILE) else "").split("\n"):
        if "=" in raw and not raw.lstrip().startswith("#"):
            a, b = raw.split("=", 1); add(a, b, "My words")
    return {"MW": W, "ME": E}

def get_mine():
    return _read(MY_FILE) if os.path.exists(MY_FILE) else "# Fennic = English, one per line. Your words win over every dialect.\n"

def save_mine(text):
    try:
        with open(MY_FILE, "w", encoding="utf-8") as f: f.write(text or "")
    except OSError as e:
        return f"Could not save: {e}"
    d = load(); d.update(load_mine())
    return f"Saved. {len(d['MW'])} word(s) in your list."

# The 19 letters from the sheet's Grammar tab, built in so the script tab works even if the sheet can't be reached
DEFAULT_LETTERS = dict(zip("mztubgelkdyraxvhons", "ɱչȶʊɮɠɛʅӄðψᵲα" "ᛪʋɦ¤ռʂ"))

def to_script(text, translate=True):
    """Latin letters -> Vel'luah script. With translate on, English is put into Vel'luah (Dark Elf dictionary) first."""
    L = {**DEFAULT_LETTERS, **load().get("DL", {})}
    conv = lambda t: "".join(L.get(c.lower(), c) for c in t)
    if not translate: return conv(text or "")
    res = to_fennic(text, [DARK])
    if res.startswith("Type"): return ""
    latin = res.split("\n")[0].replace("### ", "", 1)
    kept = {k.lower() for k in re.findall(r"\*\*(.+?)\*\*: not in the dictionary", res)}   # words with no Vel'luah entry stay in Latin letters
    script = re.sub(r"\S+", lambda m: m.group(0) if m.group(0).lower().strip(".,;:!?") in kept else conv(m.group(0)), latin)
    return f"{latin}\n{script}"

def fetch_sheet(gid, timeout=15):
    url = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=csv&gid={gid}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        text = r.read().decode("utf-8-sig", "replace")
    if text.lstrip()[:15].lower().startswith(("<!doctype", "<html")):
        raise ValueError("Google returned a web page, not the sheet (is it shared as 'anyone with the link'?)")
    return text

def load_dark():
    sources, kinds = [], set()
    for n, (title, gid, kind) in enumerate(DARK_TABS):
        cache = os.path.join(HERE, f"maparonnarn_dark_{gid}.csv")
        try:
            text, src = fetch_sheet(gid), "live Google Sheet"
            try:
                with open(cache, "w", encoding="utf-8") as f: f.write(text)
            except OSError:
                pass
        except Exception:
            text, src = None, ""
            for p, k in ((cache, "last saved copy"), (DARK_SNAPSHOTS.get(gid, ""), "bundled snapshot")):
                if p and os.path.exists(p): text, src = _read(p), k; break
        if text: sources.append((title, kind, text)); kinds.add(src)
    return dict(parse_dark(sources), dsrc=" + ".join(sorted(kinds)) or "none")

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
        _DB.update(parse_wiki(_read(WIKI_FILE)) if os.path.exists(WIKI_FILE) else {"WW": {}, "WE": {}})
        _DB.update(load_dark())
        _DB.update(load_mine())
        _DB.update(src=src, err=err, t=time.time(), stamp=time.strftime("%Y-%m-%d %H:%M"))
        return _DB

def status_md(d):
    s = f"**Source:** {d['src']} · synced {d['stamp']} · **{len(d['W'])}** words · **{len(d['P'])}** phrases · numbers {len(d['N'])}/100 · wiki list: **{len(d['WW'])}** words (bundled) · dark elf: **{len(d['DW'])}** words, **{len(d['DP'])}** phrases ({d['dsrc']}) · my words: **{len(d['MW'])}**"
    if d.get("err"): s += f"\n\n⚠️ Live sync failed ({d['err']}). Still showing the {d['src']} from {d['stamp']}."
    return s

MODES = ["Snow Elf (doc)", "Common Elven (wiki)", "Dark Elf (Vel'luah)"]
SNOW, WIKI, DARK = MODES

def _sel(mode):
    """Ticked dialects as a set (a plain string works too); nothing ticked falls back to Snow Elf."""
    sel = {mode} if isinstance(mode, str) else set(mode or [])
    return (sel & set(MODES)) or {SNOW}

def view(d, mode):
    """Words/English index for the ticked dialects. Priority when mixing: Snow Elf, then Dark Elf, then wiki."""
    sel = _sel(mode)
    parts = [(t, wk, ek) for t, wk, ek in ((SNOW, "W", "E"), (DARK, "DW", "DE"), (WIKI, "WW", "WE")) if t in sel]
    if d["MW"]: parts.insert(0, ("My words", "MW", "ME"))
    if len(parts) == 1: return d[parts[0][1]], d[parts[0][2]]
    tags = {SNOW: "snow", DARK: "dark", WIKI: "wiki", "My words": "mine"}
    W, E = {}, {}
    for t, wk, ek in parts:
        for k, e in d[wk].items():
            if k in W: W[k]["defs"] += [f"({tags[t]}) " + x for x in e["defs"]]
            else: W[k] = dict(e, defs=list(e["defs"]))
        for k, v in d[ek].items():
            lst = E.setdefault(k, [])
            lst += [f for f in v if f not in lst]
    return W, E

# ── translation ───────────────────────────────────────────────────────────
ARTICLES = {"the": "el", "a": "o", "an": "ga"}   # Vel'luah articles attach to the back of nouns
DARK_PAST, DARK_FUT = {"did", "had"}, {"shall", "gonna"}   # "was/were" and "will" have their own Vel'luah words

def attach(word, sfx):
    """Latch a suffix onto a word; if the word already ends with the suffix's first letter, that letter is skipped."""
    return word + (sfx[1:] if sfx[0].isalpha() and word.lower().endswith(sfx[0].lower()) else sfx)

def to_fennic(text, mode=MODES[0]):
    d, out, notes, tense = load(), [], [], None
    W, E = view(d, mode)
    snow = SNOW in _sel(mode)               # Snow Elf grammar wins when ticked: tense ia, plural 'len, possessive au'
    dark = DARK in _sel(mode) and not snow  # otherwise Vel'luah grammar: a'/e' tense, -zh plural, -el/-o/-ga articles, 'uhn possessive
    pos = lambda f: W.get(norm(f), {}).get("sec", "")
    pend_t = pend_a = None
    toks = re.findall(r"[A-Za-z][A-Za-z'’]*", text or "")
    i = 0
    while i < len(toks):
        raw = toks[i]; w = raw.lower().replace("’", "'"); i += 1
        if snow and w in PAST: tense = "past"; continue
        if snow and w in FUT: tense = "future"; continue
        if snow and w == "going" and i < len(toks) and toks[i].lower() == "to": tense = "future"; i += 1; continue
        if snow and w in STOP: continue
        if dark and not E.get(w):
            if w in DARK_PAST: pend_t = "a’"; continue
            if w in DARK_FUT: pend_t = "e’"; continue
            if w in ARTICLES: pend_a = ARTICLES[w]; continue
        poss = (snow or dark) and w.endswith("'s")
        if poss: w = w[:-2]
        plural = False
        c = E.get(w) or E.get(ALIAS.get(w, w))
        if not c and w in ("i", "my"): c = E.get("me")   # wiki list only has "me"
        if not c and (snow or dark) and w.endswith("s") and len(w) > 3:
            c = E.get(w[:-1]); plural = bool(c)
            if plural and dark and "/ Nouns" not in pos(c[0]): c, plural = None, False
        sec = pos(c[0]) if c else ""
        if c:
            f = c[0]
            if len(c) > 1: notes.append(f"- **{raw}**: also {', '.join(c[1:6])}")
        else:
            f = raw[:-2] if poss else raw   # not in the chosen dictionary: left in English (without its 's)
            if not raw[0].isupper(): notes.append(f"- **{raw}**: not in the dictionary, left in English")
        if plural: f = f + "’len" if snow else attach(f, "zh")
        if dark and pend_t and "/ Verbs" in sec: f, pend_t = pend_t + f, None
        if dark and pend_a and "/ Nouns" in sec: f, pend_a = attach(f, pend_a), None
        if poss: f = attach(f, "’uhn") if dark else "au’" + f
        out.append(f)
    if not out: return "Type an English sentence."
    if tense == "past": out[0] = "Ia’" + out[0]
    elif tense == "future": out[0] += "’ia"
    order = ("Word order is as typed; the Snow Elf doc's order is Subject, Object, Verb." if snow else
             "Word order is as typed; in Vel'luah the predicate follows the subject." if dark else "Word order is as typed.")
    return f"### {' '.join(out)}\n\n{order}\n\n" + "\n".join(notes)

# ── pick-which-words mode (roleplay: translate only a few words, keep the rest as typed) ──
def lookup_en(raw, E, affixes=True):
    """English word -> (Fennic form or None); handles plural 's, possessive 's and I/my."""
    w = raw.lower().replace("’", "'")
    poss = affixes and w.endswith("'s")
    if poss: w = w[:-2]
    c, plural = E.get(w) or E.get(ALIAS.get(w, w)), False
    if not c and affixes and w.endswith("s") and len(w) > 3:
        c = E.get(w[:-1]); plural = bool(c)
    if not c and w in ("i", "my"): c = E.get("me")
    if not c: return None
    f = c[0] + ("’len" if plural else "")
    return "au’" + f if poss else f

def word_options(text, mode=MODES[0]):
    _, E = view(load(), mode)
    aff = SNOW in _sel(mode)
    seen, choices = set(), []
    for raw in re.findall(r"[A-Za-z][A-Za-z'’]*", text or ""):
        w, f = raw.lower().replace("’", "'"), lookup_en(raw, E, aff)
        if f and w not in seen:
            seen.add(w); choices.append((f"{raw} → {f}", w))
    return gr.update(choices=choices, value=[])

STYLES = ["Plain", "Italics", "Bold", "With English in brackets"]

def partial(text, picks, mode=MODES[0], style=STYLES[0]):
    _, E = view(load(), mode)
    aff = SNOW in _sel(mode)
    picks = set(picks or [])
    def sub(m):
        raw = m.group(0)
        f = lookup_en(raw, E, aff) if raw.lower().replace("’", "'") in picks else None
        if not f: return raw
        return {"Italics": f"*{f}*", "Bold": f"**{f}**", "With English in brackets": f"{f} ({raw})"}.get(style, f)
    return re.sub(r"[A-Za-z][A-Za-z'’]*", sub, text or "")

def gloss_word(W, base, split=True):
    e = W.get(norm(base))
    if e: return clean_def(e["defs"][0]), "; ".join(e["defs"])
    parts = [p for p in re.split(r"[’‘'\-]", base) if p]
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
    sel = _sel(mode)
    sn, dk = SNOW in sel, DARK in sel
    if kind == "Phrases":
        rows = ([list(r) for r in d["P"]] if sn else []) + ([list(r) for r in d["DP"]] if dk else [])
    elif kind == "Numbers":
        rows = ([[w, str(n), "Snow Elf numbers"] for n, w in sorted(d["N"].items())] if sn else []) + ([[w, str(n), "Dark Elf (Vel'luah) numerals"] for n, w in sorted(d["DN"].items())] if dk else [])
    elif kind == "Affixes":
        rows = ([[a, b, "Prefix/Suffix"] for a, b in d["A"]] if sn else []) + ([[a, b, "Vel'luah suffixes"] for a, b in d["DA"]] if dk else [])
    elif kind == "Overlaps":
        seen = {}
        for t, wk in ((SNOW, "W"), (DARK, "DW"), (WIKI, "WW")):
            if t in sel:
                for k, e in d[wk].items(): seen.setdefault(k, []).append((t.split(" (")[0], e))
        rows = [[v[0][1]["form"], " | ".join(f"{t}: " + "; ".join(e["defs"]) for t, e in v), "Overlap"] for k, v in sorted(seen.items()) if len(v) > 1]
    else: rows = [[e["form"], "; ".join(e["defs"]), e["sec"]] for e in sorted(W.values(), key=lambda e: norm(e["form"]))]
    if f: rows = [r for r in rows if f in " ".join(r).lower()]
    return rows[:1000]

def snow_number(v, d):
    if v >= 10**10: return "Use 0 to 9,999,999,999."
    if len(d["N"]) < 100: return "The doc's 0-99 table is incomplete."
    s, groups = str(v), []
    while s: groups.insert(0, int(s[-2:])); s = s[:-2]
    sfx = ["", "’firr", "’ilk", "’elam", "’karr"]
    return ", ".join(d["N"][g] + sfx[len(groups) - 1 - i] for i, g in enumerate(groups))

def dark_number(v, d):
    """Vel'luah: number words 0-10, factor suffixes -ah (10s) -ee (100s) -he (1000s), factors joined by hyphens, zero places skipped."""
    N = d["DN"]
    if len(N) < 11: return "The Vel'luah number words are not loaded."
    if v == 0: return N[0]
    if v >= 10000: return "The sheet's rules are only clear up to 9,999."
    th, r = divmod(v, 1000); h, r = divmod(r, 100); t, u = divmod(r, 10)
    parts = []
    if th: parts.append(attach(N[th], "he"))
    if h: parts.append(attach(N[h], "ee"))
    if t == 1 and u == 0: parts.append(N[10])   # ten has its own word
    elif t: parts.append(attach(N[t], "ah"))
    if u: parts.append(N[u])
    return "-".join(parts)

def number(n, mode=MODES[0]):
    d, sel, lines = load(), _sel(mode), []
    try: v = int(str(n).strip().replace(",", ""))
    except ValueError: return "Enter a whole number."
    if v < 0: return "Use a whole number from 0 up."
    if SNOW in sel: lines.append(f"{SNOW}: {snow_number(v, d)}")
    if DARK in sel: lines.append(f"{DARK}: {dark_number(v, d)}")
    if WIKI in sel: lines.append(f"{WIKI}: the wiki list has number words but no number system, so there is no converter.")
    return "\n".join(lines)

def grammar_text(d, mode):
    sel, out = _sel(mode), []
    if SNOW in sel: out.append("══ Snow Elf (doc) ══\n" + (d["G"] or "(no grammar loaded)"))
    if DARK in sel: out.append("══ Dark Elf (Vel'luah) ══\n" + (d["DG"] or "(Grammar tab not loaded; check the sheet is shared as 'anyone with the link')"))
    if WIKI in sel: out.append("══ Common Elven (wiki) ══\nNo grammar notes are bundled for the wiki list. It is used as a plain word list, and the Snow Elf and Vel'luah rules are not applied to it.")
    return "\n\n".join(out)

def do_sync(kind, flt, mode=MODES[0]):
    d = load(force=True)
    return status_md(d), browse(kind, flt, mode), grammar_text(d, mode)

def refresh(kind, flt, mode=MODES[0]):
    d = load()
    return status_md(d), browse(kind, flt, mode), grammar_text(d, mode)

# ── UI ────────────────────────────────────────────────────────────────────
with gr.Blocks(title="Maparonnarn · Fennic Elven") as demo:
    gr.Markdown("# Maparonnarn · Fennic Elven (Snow Elf dialect)")
    status = gr.Markdown()
    sync_btn = gr.Button("🔄 Sync from Google Doc")
    mode = gr.CheckboxGroup(MODES, value=[MODES[0]], label="Dialects: tick one, or two or three to mix them (Snow Elf wins, then Dark Elf, then wiki)")
    with gr.Tabs():
        with gr.Tab("Translate"):
            e_in = gr.Textbox(label="English → Fennic", placeholder="I was cold")
            e_btn = gr.Button("Translate to Fennic")
            e_out = gr.Markdown()
            pick_btn = gr.Button("Or pick which words to translate…")
            pick = gr.Dropdown(multiselect=True, allow_custom_value=True, choices=[], label="Pick the words to translate (the rest stay as typed). You can also type a word.")
            style = gr.Radio(STYLES, value=STYLES[0], label="Output style")
            p_out = gr.Textbox(label="Your sentence", lines=3, interactive=False, show_copy_button=True)
            f_in = gr.Textbox(label="Fennic → English", placeholder="Ia’Ayred ehyubor")
            f_btn = gr.Button("Translate to English")
            f_out = gr.Markdown()
        with gr.Tab("Search"):
            q = gr.Textbox(label="Word (either language)")
            q_btn = gr.Button("Search")
            q_out = gr.Markdown()
        with gr.Tab("Browse"):
            kind = gr.Radio(["Words", "Phrases", "Numbers", "Affixes", "Overlaps"], value="Words", label="Show")
            flt = gr.Textbox(label="Filter")
            table = gr.Dataframe(headers=["Fennic", "English", "Section"], interactive=False, wrap=True)
        with gr.Tab("Numbers"):
            n_in = gr.Textbox(label="Number (written in each language ticked above)", placeholder="1203")
            n_btn = gr.Button("Write in Fennic")
            n_out = gr.Textbox(label="Result, by language", lines=3, interactive=False)
        with gr.Tab("My words"):
            gr.Markdown("One per line: `Fennic = English`. Your words win over every dialect. Saved next to the app (on a free host the file can reset when it restarts).")
            mine = gr.Textbox(lines=14, label="my_words.txt")
            mine_btn = gr.Button("Save my words")
            mine_msg = gr.Markdown()
        with gr.Tab("Vel'luah script"):
            sc_in = gr.Textbox(label="English, or Vel'luah in Latin letters", placeholder="good thanks")
            sc_tr = gr.Checkbox(label="Translate from English first (Dark Elf dictionary)", value=True)
            sc_out = gr.Textbox(label="Vel'luah (Latin) and script", lines=2, interactive=False, show_copy_button=True)
            gr.Markdown("With translation on, the first line is the Vel'luah and the second is the script. Words the dictionary doesn't have stay in English letters. Letters with no glyph stay as typed.")
        with gr.Tab("Grammar"):
            gram = gr.Textbox(label="Grammar notes (follow the dialects ticked above)", lines=28, interactive=False)
    outs = [status, table, gram]
    sync_btn.click(do_sync, [kind, flt, mode], outs, api_name=False)
    demo.load(refresh, [kind, flt, mode], outs, api_name=False)
    mode.change(refresh, [kind, flt, mode], outs, api_name=False)
    kind.change(refresh, [kind, flt, mode], outs, api_name=False)
    flt.change(refresh, [kind, flt, mode], outs, api_name=False)
    e_btn.click(to_fennic, [e_in, mode], e_out, api_name=False); e_in.submit(to_fennic, [e_in, mode], e_out, api_name=False)
    pick_btn.click(word_options, [e_in, mode], pick, api_name=False)
    pick.change(partial, [e_in, pick, mode, style], p_out, api_name=False)
    style.change(partial, [e_in, pick, mode, style], p_out, api_name=False)
    mine_btn.click(save_mine, mine, mine_msg, api_name=False)
    demo.load(get_mine, None, mine, api_name=False)
    sc_in.change(to_script, [sc_in, sc_tr], sc_out, api_name=False)
    sc_tr.change(to_script, [sc_in, sc_tr], sc_out, api_name=False)
    f_btn.click(to_english, [f_in, mode], f_out, api_name=False); f_in.submit(to_english, [f_in, mode], f_out, api_name=False)
    q_btn.click(search, [q, mode], q_out, api_name=False); q.submit(search, [q, mode], q_out, api_name=False)
    n_btn.click(number, [n_in, mode], n_out, api_name=False); n_in.submit(number, [n_in, mode], n_out, api_name=False)

if __name__ == "__main__":
    # Render/other hosts set PORT; locally this falls back to 7860 (same as before)
    demo.launch(server_name="0.0.0.0", server_port=int(os.environ.get("PORT", 7860)))
