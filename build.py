#!/usr/bin/env python3
"""
Genealogy Tree Builder — parses CSV, generates HTML with original dark theme.
RULES:
  - Any cell with ":" is a CODE, next column is the NAME.
  - Rows 1-2 are special root: code "0" and "0a".
  - Code ending with DIGIT → blood family member.
  - Code ending with LETTER (a/b) → spouse (non-blood).
  - Children's codes start with their parent's SPOUSE code + ":".
    e.g. children of 0a:01 (married to 0a:01a) have codes 0a:01a:01, 0a:01a:02…
  - Multiple marriages: same person code appears twice with different spouse suffixes
    e.g. 0a:04 appears with 0a:04a AND 0a:04b.
"""

import csv
import json
import re
from datetime import datetime
from collections import OrderedDict, defaultdict
from pathlib import Path

CSV_PATH = Path(
    "/Users/nandha_handharu/Documents/Nandha/GitHub/astro-platform-starter/Keluarga H. Mardjono Siradj - Seluruh Keluarga.csv")
OUT_PATH = Path(
    "/Users/nandha_handharu/Documents/Nandha/GitHub/astro-platform-starter/index.html")

# ── Parse CSV ─────────────────────────────────────────────────────────────────


def parse_csv(path):
    """Parse CSV. Track order and detect duplicate person codes (multi-marriage)."""
    entries = OrderedDict()          # code → {name, …}
    code_order = []                  # list of (code, is_duplicate)
    seen_codes = set()
    duplicate_person_codes = set()   # person codes that appear >1 time

    with open(path, 'r', encoding='utf-8-sig') as f:
        reader = csv.reader(f)
        next(reader)  # skip header
        for row in reader:
            while len(row) < 12:
                row.append('')
            code = name = None
            if row[0].strip() in ('0', '0a'):
                code = row[0].strip()
                name = row[1].strip()
            else:
                for ci in range(5):
                    cell = row[ci].strip()
                    if ':' in cell:
                        code = cell
                        name = row[ci + 1].strip() if ci + 1 < len(row) else ''
                        break
            if code is None or not name:
                # Still record code-only rows (for order tracking)
                if code and not name:
                    code_order.append((code, code in seen_codes))
                    seen_codes.add(code)
                continue

            is_dup = code in seen_codes
            if is_dup and code[-1].isdigit():
                duplicate_person_codes.add(code)

            code_order.append((code, is_dup))
            seen_codes.add(code)

            entries[code] = {
                'name': name,
                'bp': row[6].strip(), 'bd': row[7].strip(),
                'dp': row[8].strip(), 'dd': row[9].strip(),
                'addr': row[10].strip(), 'ph': row[11].strip(),
            }
    return entries, code_order, duplicate_person_codes


def classify(entries, code_order, duplicate_person_codes):
    """
    Classify each code as blood (ends with digit) or spouse (ends with letter).
    Build: persons dict, spouses_of dict, marriages dict.

    Special handling for Purwastuti-style multi-marriages where the same person code
    appears twice in the CSV with different spouse codes that don't follow the simple
    {person_code}+letter pattern (e.g. 0a:02a:01 with spouses 0a:02a:01a AND 0a:02a:02b).
    """
    all_codes = set(entries.keys())
    # code → entry  (blood members, code ends with digit or is "0")
    persons = {}
    spouses = {}       # code → entry  (spouse, code ends with letter)

    for code, entry in entries.items():
        if code == '0':
            persons[code] = entry
        elif code[-1].isdigit():
            persons[code] = entry
        else:
            spouses[code] = entry

    # Build marriages: person_code → [(spouse_code, spouse_entry)]
    marriages = defaultdict(list)  # person_code → [spouse_code, …]
    spouse_of = {}                  # spouse_code → person_code

    for sp_code in spouses:
        if sp_code == '0a':
            person_code = '0'
        else:
            person_code = re.sub(r'[a-z]+$', '', sp_code)
        spouse_of[sp_code] = person_code
        marriages[person_code].append(sp_code)

    # Detect Purwastuti-style multi-marriages:
    # When a person code (ending in digit) appears twice in the CSV,
    # the spouse code that follows the SECOND occurrence belongs to this person.
    # Use code_order to find the spouse after the duplicate.
    for dup_code in duplicate_person_codes:
        found_first = False
        for i, (code, is_dup) in enumerate(code_order):
            if code == dup_code:
                if found_first:
                    # This is the second occurrence — find the next spouse code
                    for j in range(i+1, len(code_order)):
                        next_code = code_order[j][0]
                        if next_code in spouses:
                            old_person = spouse_of.get(next_code)
                            if old_person != dup_code:
                                if old_person in marriages and next_code in marriages[old_person]:
                                    marriages[old_person].remove(next_code)
                                spouse_of[next_code] = dup_code
                                if next_code not in marriages[dup_code]:
                                    marriages[dup_code].append(next_code)
                            break
                        elif next_code in persons and next_code != dup_code:
                            break
                else:
                    found_first = True

    # Build children: for each person, children are NON-SPOUSE codes starting with
    # one of their spouse codes + ":"
    children_of = defaultdict(list)
    children_via = defaultdict(lambda: defaultdict(list))

    for p_code in persons:
        for sp_code in marriages.get(p_code, []):
            prefix = sp_code + ':'
            for child_code in persons:
                if child_code == p_code:
                    continue
                if child_code.startswith(prefix):
                    remainder = child_code[len(prefix):]
                    if ':' not in remainder:
                        children_of[p_code].append(child_code)
                        children_via[p_code][sp_code].append(child_code)

    return persons, spouses, marriages, spouse_of, children_of, children_via

# ── Generate HTML ─────────────────────────────────────────────────────────────


def build_tooltip(entry, sp_entry=None):
    """Build tooltip text for a person."""
    lines = []
    if entry.get('bd'):
        lines.append(
            f"Born: {entry['bd']}" + (f" — {entry['bp']}" if entry.get('bp') else ''))
    elif entry.get('bp'):
        lines.append(f"Birthplace: {entry['bp']}")
    if entry.get('dd'):
        lines.append(
            f"Died: {entry['dd']}" + (f" — {entry['dp']}" if entry.get('dp') else ''))
    elif entry.get('dp'):
        lines.append(f"Deathplace: {entry['dp']}")
    if entry.get('addr'):
        lines.append(f"Address: {entry['addr'].replace(chr(10), ', ')}")
    if entry.get('ph'):
        lines.append(f"Phone: {entry['ph']}")
    return '\\n'.join(lines)


def esc(s):
    return s.replace('&', '&').replace('<', '<').replace('>', '>').replace('"', '"').replace("'", "&#39;")


def is_deceased(entry):
    return bool(entry.get('dd') or entry.get('dp'))


def generate(persons, spouses, marriages, spouse_of, children_of, children_via, entries):
    """Build the complete JSON for embedding."""
    data = {
        'persons': {},
        'spouses': {},
        'marriages': {},
        'children_via': {},
        'multi_marriages': [],
    }
    for code, e in persons.items():
        data['persons'][code] = {
            'name': e['name'], 'bp': e.get('bp', ''), 'bd': e.get('bd', ''),
            'dp': e.get('dp', ''), 'dd': e.get('dd', ''),
            'addr': e.get('addr', ''), 'ph': e.get('ph', ''),
        }
    for code, e in spouses.items():
        data['spouses'][code] = {
            'name': e['name'], 'bp': e.get('bp', ''), 'bd': e.get('bd', ''),
            'dp': e.get('dp', ''), 'dd': e.get('dd', ''),
            'addr': e.get('addr', ''), 'ph': e.get('ph', ''),
            'of': spouse_of.get(code, ''),
        }
    for p_code, sp_list in marriages.items():
        data['marriages'][p_code] = sp_list
    for p_code, via in children_via.items():
        data['children_via'][p_code] = {sp: kids for sp, kids in via.items()}
    # Detect multi-marriages
    for p_code, sp_list in marriages.items():
        if len(sp_list) > 1:
            data['multi_marriages'].append(p_code)
    return data


def write_html(data, out_path):
    data_json = json.dumps(data, ensure_ascii=False)
    timestamp = datetime.now().strftime("%-d/%b/%Y %H:%M:%S")

    html = r'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Bani H. Siradj Mardjono - Family Tree</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:'Segoe UI',Tahoma,sans-serif;background:linear-gradient(135deg,#1a1a2e,#16213e);color:#e0e0e0;min-height:100vh}
.container{max-width:100%;margin:0 auto;background:rgba(26,26,46,0.95);min-height:100vh}
.header{background:linear-gradient(135deg,rgba(45,125,110,0.8),rgba(212,175,55,0.1));padding:24px;text-align:center;border-bottom:2px solid #d4af37}
.header h1{color:#d4af37;font-size:2em;text-shadow:2px 2px 4px rgba(0,0,0,0.5)}
.header p{color:#b8956a;font-size:1em;margin-top:4px}
.tabs{display:flex;border-bottom:2px solid #2d7d6e;background:rgba(0,0,0,0.3)}
.tab-btn{flex:1;padding:14px;background:none;border:none;color:#888;font-size:1em;cursor:pointer;transition:all 0.3s}
.tab-btn:hover{color:#d4af37;background:rgba(212,175,55,0.05)}
.tab-btn.active{color:#d4af37;border-bottom:3px solid #d4af37;background:rgba(212,175,55,0.1)}
.tab-panel{display:none;padding:20px}
.tab-panel.active{display:block}
.stats-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:15px;margin-bottom:20px}
.stat-card{background:linear-gradient(135deg,rgba(45,125,110,0.15),rgba(212,175,55,0.05));padding:20px;border-radius:8px;text-align:center;border:1px solid rgba(45,125,110,0.3)}
.stat-card h3{color:#b8956a;font-size:0.85em;margin-bottom:6px;text-transform:uppercase}
.stat-card .num{color:#d4af37;font-size:2.2em;font-weight:700}
.breakdown{background:rgba(0,0,0,0.2);border:1px solid rgba(45,125,110,0.3);border-radius:8px;padding:20px;margin-bottom:15px}
.breakdown h3{color:#d4af37;margin-bottom:12px;font-size:1.1em}
.brow{display:flex;justify-content:space-between;padding:8px 12px;border-bottom:1px solid rgba(255,255,255,0.05)}
.brow:last-child{border-bottom:none}
.brow .bl{color:#b8956a}.brow .bv{color:#d4af37;font-weight:600}
.tree-toolbar{display:flex;flex-direction:column;gap:8px;margin-bottom:15px}
.tree-toolbar-row{display:flex;gap:6px;align-items:center;flex-wrap:wrap}
.tree-toolbar input{flex:1;min-width:200px;padding:10px 15px;background:rgba(0,0,0,0.3);border:1px solid #2d7d6e;border-radius:4px;color:#e0e0e0;font-size:1em}
.tree-toolbar input::placeholder{color:#666}
.tree-toolbar button,.action-btn{padding:10px 20px;background:#2d7d6e;color:#d4af37;border:none;border-radius:4px;cursor:pointer;font-weight:600;transition:all 0.3s;white-space:nowrap}
.tree-toolbar button:hover,.action-btn:hover{background:#3d8d7e}
.search-bar{display:flex;gap:8px;align-items:center;max-height:0;opacity:0;overflow:hidden;transition:max-height 0.35s ease,opacity 0.25s ease}
.search-bar.open{max-height:60px;opacity:1}
.search-bar input{flex:1;min-width:0;padding:10px 15px;background:rgba(0,0,0,0.3);border:1px solid #2d7d6e;border-radius:4px;color:#e0e0e0;font-size:1em}
.search-bar input::placeholder{color:#666}
.tree-wrap{overflow:hidden;background:rgba(0,0,0,0.2);border:1px solid rgba(45,125,110,0.3);border-radius:8px;max-height:80vh;position:relative;cursor:grab;touch-action:none;user-select:none;-webkit-user-select:none}
.tree-wrap.grabbing{cursor:grabbing}
.tree-wrap-inner{display:inline-block;min-width:100%;transform-origin:0 0;will-change:transform}
.abbr-box{color:#d4af37;font-size:0.75em;font-weight:700;letter-spacing:0.03em}
.ftree{display:flex;flex-direction:column;align-items:center;min-width:max-content;padding:0 40px}
.ftree ul{display:flex;padding-top:20px;position:relative;transition:all 0.5s}
.ftree ul::before{content:'';position:absolute;top:0;left:50%;border-left:2px solid #2d7d6e;height:20px}
.ftree li{display:flex;flex-direction:column;align-items:center;position:relative;padding:20px 8px 0;float:left;text-align:center;list-style:none}
.ftree li::before,.ftree li::after{content:'';position:absolute;top:0;right:50%;border-top:2px solid #2d7d6e;width:50%;height:20px}
.ftree li::after{right:auto;left:50%;border-left:2px solid #2d7d6e}
.ftree li:only-child::before,.ftree li:only-child::after{display:none}
.ftree li:only-child{padding-top:0}
.ftree li:first-child::before,.ftree li:last-child::after{border:0 none}
.ftree li:last-child::before{border-right:2px solid #2d7d6e;border-radius:0 5px 0 0}
.ftree li:first-child::after{border-radius:5px 0 0 0}
.ftree ul ul::before{content:'';position:absolute;top:0;left:50%;border-left:2px solid #2d7d6e;height:20px}
.couple{display:flex;align-items:center;gap:0;border:1px solid #2d7d6e;border-radius:6px;background:linear-gradient(135deg,rgba(212,175,55,0.08),rgba(45,125,110,0.08));position:relative;cursor:default;transition:all 0.2s;white-space:nowrap}
.couple:hover{border-color:#d4af37;box-shadow:0 2px 12px rgba(212,175,55,0.2)}
.pbox{padding:6px 12px;font-size:0.82em;position:relative}
.pbox.blood{color:#d4af37;font-weight:600}
.pbox.nonblood{color:#7b8fa3;font-weight:500;border-left:1px solid rgba(45,125,110,0.4)}
.pbox .di{color:#999;font-size:0.9em;margin-left:2px}
.couple .eq{color:#2d7d6e;font-size:0.9em;padding:0 2px;font-weight:bold}
.couple.search-hit{background:rgba(212,175,55,0.25);border-color:#d4af37;box-shadow:0 0 12px rgba(212,175,55,0.4)}
.tbtn{display:inline-flex;align-items:center;justify-content:center;width:18px;height:18px;border-radius:50%;background:#2d7d6e;color:#d4af37;border:none;cursor:pointer;font-size:0.7em;margin-top:4px;transition:all 0.2s}
.tbtn:hover{background:#d4af37;color:#1a1a2e}
.tip{position:absolute;bottom:calc(100% + 8px);left:50%;transform:translateX(-50%);background:rgba(10,10,20,0.95);color:#e0e0e0;padding:12px 16px;border-radius:6px;font-size:0.8em;white-space:nowrap;z-index:9999;border:1px solid #d4af37;box-shadow:0 4px 20px rgba(0,0,0,0.8);opacity:0;pointer-events:none;transition:opacity 0.15s;text-align:left;line-height:1.5}
.tip::after{content:'';position:absolute;top:100%;left:50%;transform:translateX(-50%);border:6px solid transparent;border-top-color:#d4af37}
.couple:hover .tip{opacity:1}
.tip.visible{opacity:1;pointer-events:auto}
.tip .tname{color:#d4af37;font-weight:600;font-size:1em;display:block;margin-bottom:4px}
.tip .trow{color:#ccc}.tip .tlbl{color:#888}
.multi-branches{display:flex;justify-content:center;gap:0;padding-top:20px;position:relative}
.multi-branches::before{content:'';position:absolute;top:0;left:50%;border-left:2px solid #2d7d6e;height:20px}
.mbranch{display:flex;flex-direction:column;align-items:center;position:relative;padding:20px 8px 0}
.mbranch::before,.mbranch::after{content:'';position:absolute;top:0;right:50%;border-top:2px solid #2d7d6e;width:50%;height:20px}
.mbranch::after{right:auto;left:50%;border-left:2px solid #2d7d6e}
.mbranch:first-child::before{border:0 none}
.mbranch:first-child::after{border-radius:5px 0 0 0}
.mbranch:last-child::after{border:0 none}
.mbranch:last-child::before{border-right:2px solid #2d7d6e;border-radius:0 5px 0 0}
.mbranch:only-child::before,.mbranch:only-child::after{display:none}
.mbranch:only-child{padding-top:0}
.mbranch-empty{width:20px;height:10px}
.ie-grid{display:grid;grid-template-columns:1fr 1fr;gap:25px}
.ie-box{background:rgba(45,125,110,0.08);padding:25px;border-radius:8px;border:1px solid rgba(45,125,110,0.3)}
.ie-box h3{color:#d4af37;margin-bottom:15px}
.dropzone{border:2px dashed #2d7d6e;border-radius:8px;padding:40px 20px;text-align:center;cursor:pointer;transition:all 0.3s;color:#888}
.dropzone.dragover{border-color:#d4af37;background:rgba(212,175,55,0.05)}
.file-label{display:inline-block;padding:10px 20px;background:#2d7d6e;color:#d4af37;border-radius:4px;cursor:pointer;margin-top:10px;font-weight:600}
.file-label:hover{background:#3d8d7e}
.file-label input{display:none}
.export-btn{display:block;padding:12px 24px;background:#2d7d6e;color:#d4af37;border:none;border-radius:4px;cursor:pointer;font-weight:600;font-size:1em;margin-bottom:10px;width:100%;transition:all 0.3s}
.export-btn:hover{background:#3d8d7e}
.status{padding:10px;border-radius:4px;margin-top:10px;display:none;font-size:0.9em}
.status.ok{display:block;background:rgba(45,125,110,0.2);border:1px solid #2d7d6e;color:#8fd}
.status.err{display:block;background:rgba(200,50,50,0.2);border:1px solid #d9534f;color:#f99}
@media(max-width:768px){.stats-grid{grid-template-columns:repeat(2,1fr)}.ie-grid{grid-template-columns:1fr}.tab-btn{font-size:0.85em;padding:12px 6px}}
</style>
</head>
<body>
<div class="container">
  <div class="header">
    <h1>✨ Bani H. Siradj Mardjono ✨</h1>
    <p>Silsilah Keluarga — Islamic Heritage Family Archive</p>
    <p style="color:#666;font-size:0.75em;margin-top:6px">Updated on ''' + timestamp + r'''</p>
  </div>
  <div class="tabs">
    <button class="tab-btn active" onclick="switchTab(0,this)">📊 Dashboard</button>
    <button class="tab-btn" onclick="switchTab(1,this)">🌳 Family Tree</button>
    <button class="tab-btn" onclick="switchTab(2,this)">📤 Import / Export</button>
  </div>
  <div id="tab-0" class="tab-panel active">
    <div class="stats-grid">
      <div class="stat-card"><h3>Total Members</h3><span class="num" id="s-total">0</span></div>
      <div class="stat-card"><h3>Living</h3><span class="num" id="s-living">0</span></div>
      <div class="stat-card"><h3>Deceased</h3><span class="num" id="s-deceased">0</span></div>
      <div class="stat-card"><h3>Generations</h3><span class="num" id="s-gens">0</span></div>
    </div>
    <div class="breakdown"><h3>Generation Breakdown</h3><div id="gen-list"></div></div>
    <div class="breakdown"><h3>Geographic Distribution (Birth Place)</h3><div id="geo-list"></div></div>
  </div>
  <div id="tab-1" class="tab-panel">
    <div class="tree-toolbar">
      <div class="tree-toolbar-row">
        <button onclick="toggleSearch()" title="Search">🔍</button>
        <button onclick="expandAll()">Expand All</button>
        <button onclick="collapseAll()">Collapse All</button>
        <span style="border-left:1px solid #2d7d6e;height:24px;margin:0 2px;flex-shrink:0"></span>
        <button onclick="zoomOut()">−</button>
        <span id="zoom-level" style="color:#d4af37;font-size:0.85em;min-width:36px;text-align:center;flex-shrink:0">100%</span>
        <button onclick="zoomIn()">+</button>
        <button onclick="zoomReset()">↺</button>
        <span style="border-left:1px solid #2d7d6e;height:24px;margin:0 2px;flex-shrink:0"></span>
        <button onclick="toggleAbbr()" id="abbr-btn" title="Toggle abbreviations">Abbr</button>
      </div>
      <div class="search-bar" id="search-bar">
        <input id="search-in" placeholder="Search by name..." onkeyup="if(event.key==='Enter')doSearch()"/>
        <button onclick="doSearch()">Go</button>
        <button onclick="clearSearch()" style="background:#555">✕</button>
      </div>
    </div>
    <div class="tree-wrap">
      <div class="tree-wrap-inner">
        <div class="ftree" id="tree"></div>
      </div>
    </div>
  </div>
  <div id="tab-2" class="tab-panel">
    <div class="ie-grid">
      <div class="ie-box">
        <h3>📥 Import CSV</h3>
        <div class="dropzone" id="dropzone">
          <p>Drag & drop your CSV file here</p>
          <p style="color:#666;font-size:0.9em">or</p>
          <label class="file-label">Choose File<input type="file" accept=".csv" onchange="onFileSelect(event)"/></label>
        </div>
        <div class="status" id="import-status"></div>
      </div>
      <div class="ie-box">
        <h3>📤 Export Data</h3>
        <p style="color:#b8956a;margin-bottom:15px">Download family tree data as JSON</p>
        <button class="export-btn" onclick="exportJSON()">💾 Download JSON</button>
      </div>
    </div>
  </div>
</div>
<script>
const D = ''' + data_json + r''';

const P = D.persons;   // code→{name,bp,bd,dp,dd,addr,ph}
const S = D.spouses;   // code→{name,bp,bd,dp,dd,addr,ph,of}
const M = D.marriages; // personCode→[spouseCode,…]
const CV = D.children_via; // personCode→{spouseCode→[childCode,…]}
const MM = new Set(D.multi_marriages); // set of person codes with >1 marriage

let searchHits = new Set();

function switchTab(i,btn){
  document.querySelectorAll('.tab-panel').forEach(p=>p.classList.remove('active'));
  document.querySelectorAll('.tab-btn').forEach(b=>b.classList.remove('active'));
  document.getElementById('tab-'+i).classList.add('active');
  if(btn) btn.classList.add('active');
}

function isDead(e){return !!(e.dd||e.dp)}

function tipHTML(code){
  const e = P[code] || S[code];
  if(!e) return '';
  let h='<span class="tname">'+esc(e.name)+'</span>';
  if(P[code] && M[code]){
    M[code].forEach(sc=>{
      const sp=S[sc];
      if(sp) h+='<div class="trow"><span class="tlbl">Spouse: </span>'+esc(sp.name)+'</div>';
    });
  }
  if(e.bd) h+='<div class="trow"><span class="tlbl">Born: </span>'+esc(e.bd)+(e.bp?' — '+esc(e.bp):'')+'</div>';
  else if(e.bp) h+='<div class="trow"><span class="tlbl">Birthplace: </span>'+esc(e.bp)+'</div>';
  if(e.dd) h+='<div class="trow"><span class="tlbl">Died: </span>'+esc(e.dd)+(e.dp?' — '+esc(e.dp):'')+'</div>';
  else if(e.dp) h+='<div class="trow"><span class="tlbl">Deathplace: </span>'+esc(e.dp)+'</div>';
  if(e.addr) h+='<div class="trow"><span class="tlbl">Address: </span>'+esc(e.addr.replace(/\n/g,', '))+'</div>';
  if(e.ph) h+='<div class="trow"><span class="tlbl">Phone: </span>'+esc(e.ph)+'</div>';
  return h;
}
function esc(s){return s.replace(/&/g,'&').replace(/</g,'<').replace(/>/g,'>').replace(/"/g,'"');}

function nameBox(code, isBlood){
  const e = P[code] || S[code];
  if(!e) return '';
  const cls = isBlood ? 'blood' : 'nonblood';
  const dead = isDead(e) ? '<span class="di"> 🕊</span>' : '';
  const label = showAbbr
    ? '<span class="abbr-box">'+esc(toAbbr(e.name))+'</span>'
    : esc(e.name);
  return '<div class="pbox '+cls+'">'+label+dead+'</div>';
}

function renderBranch(pCode){
  const pe = P[pCode];
  if(!pe) return '';
  const spouses = M[pCode] || [];
  const hit = searchHits.has(pCode) || spouses.some(sc=>searchHits.has(sc));
  const isMulti = MM.has(pCode);

  let coupleHTML = '<div class="couple'+(hit?' search-hit':'')+'">';
  coupleHTML += '<div class="tip">'+tipHTML(pCode)+'</div>';

  if(isMulti && spouses.length >= 2){
    // Single merged couple box: [Spouse1] = [Person] = [Spouse2]
    const sp0 = S[spouses[0]];
    if(sp0){
      coupleHTML += nameBox(spouses[0], false);
      coupleHTML += '<span class="eq">\u2550</span>';
    }
    coupleHTML += nameBox(pCode, true);
    const sp1 = S[spouses[1]];
    if(sp1){
      coupleHTML += '<span class="eq">\u2550</span>';
      coupleHTML += nameBox(spouses[1], false);
    }
    coupleHTML += '</div>';

    // Wrapper: two collapsible branches side by side
    let childBlocks = '<div class="multi-branches">';
    spouses.forEach((sc)=>{
      const sp = S[sc];
      const kids = (CV[pCode] && CV[pCode][sc]) || [];
      const label = sp ? sp.name : '';
      childBlocks += '<div class="mbranch">';
      if(kids.length > 0){
        childBlocks += '<button class="tbtn" onclick="toggleBranch(this)" title="w/ '+esc(label)+'">\u2212</button>';
        childBlocks += '<ul>';
        kids.forEach(ck=>{ childBlocks += '<li>'+renderBranch(ck)+'</li>'; });
        childBlocks += '</ul>';
      } else {
        childBlocks += '<div class="mbranch-empty" title="w/ '+esc(label)+' (no children)"></div>';
      }
      childBlocks += '</div>';
    });
    childBlocks += '</div>';
    return coupleHTML + childBlocks;

  } else {
    // Single marriage or no spouse
    coupleHTML += nameBox(pCode, true);
    if(spouses.length === 1){
      coupleHTML += '<span class="eq">═</span>';
      coupleHTML += nameBox(spouses[0], false);
    }
    coupleHTML += '</div>';

    // Children
    let allKids = [];
    spouses.forEach(sc=>{
      const kids = (CV[pCode] && CV[pCode][sc]) || [];
      allKids = allKids.concat(kids);
    });

    let childrenHTML = '';
    if(allKids.length > 0){
      childrenHTML = '<ul>';
      allKids.forEach(ck=>{ childrenHTML += '<li>'+renderBranch(ck)+'</li>'; });
      childrenHTML += '</ul>';
    }

    let toggleHTML = '';
    if(childrenHTML){
      toggleHTML = '<button class="tbtn" onclick="toggleBranch(this)">−</button>';
    }
    return coupleHTML + toggleHTML + childrenHTML;
  }
}

function renderTree(){
  document.getElementById('tree').innerHTML = renderBranch('0');
}

function toggleBranch(btn){
  const el = btn.nextElementSibling;
  if(!el) return;
  if(el.style.display==='none'){el.style.display='';btn.textContent='−';}
  else{el.style.display='none';btn.textContent='+';}
}
function expandAll(){
  document.querySelectorAll('.ftree ul').forEach(u=>u.style.display='');
  document.querySelectorAll('.tbtn').forEach(b=>b.textContent='−');
}
function collapseAll(){
  document.querySelectorAll('.ftree ul ul').forEach(u=>u.style.display='none');
  document.querySelectorAll('.tbtn').forEach(b=>b.textContent='+');
  const first=document.querySelector('.ftree > .tbtn');
  if(first){first.textContent='−';const n=first.nextElementSibling;if(n)n.style.display='';}
}

function doSearch(){
  const q=document.getElementById('search-in').value.trim().toLowerCase();
  searchHits.clear();
  if(q){
    for(const[c,e]of Object.entries(P)){if(e.name.toLowerCase().includes(q))searchHits.add(c);}
    for(const[c,e]of Object.entries(S)){if(e.name.toLowerCase().includes(q))searchHits.add(c);}
  }
  renderTree();
  if(searchHits.size>0){expandAll();setTimeout(()=>{ panToHit(); },150);}
}
function clearSearch(){document.getElementById('search-in').value='';searchHits.clear();renderTree();}

function updateDashboard(){
  const allP=Object.values(P);
  const allS=Object.values(S);
  const everyone=[...allP,...allS];
  const total=everyone.length;
  let deceased=0; everyone.forEach(e=>{if(e.dd||e.dp)deceased++;});
  document.getElementById('s-total').textContent=total;
  document.getElementById('s-living').textContent=total-deceased;
  document.getElementById('s-deceased').textContent=deceased;
  // Generations by colon depth
  let maxG=0;
  const gc={};
  allP.forEach(e=>{
    // find its code
  });
  // Simpler: count by code depth
  for(const code of Object.keys(P)){
    const g = (code.match(/:/g)||[]).length;
    if(g>maxG) maxG=g;
    gc[g]=(gc[g]||0)+1;
  }
  document.getElementById('s-gens').textContent=maxG;
  const genLabels={0:'Patriarch',1:'Children',2:'Grandchildren',3:'Great-Grandchildren',4:'Great-Great-Grandchildren',5:'Gen 5'};
  let gh='';
  Object.keys(gc).sort((a,b)=>a-b).forEach(g=>{
    gh+='<div class="brow"><span class="bl">Gen '+g+' — '+(genLabels[g]||'Gen '+g)+'</span><span class="bv">'+gc[g]+'</span></div>';
  });
  document.getElementById('gen-list').innerHTML=gh;
  // Geo
  const geo={};
  everyone.forEach(e=>{if(e.bp)geo[e.bp]=(geo[e.bp]||0)+1;});
  let gg='';
  Object.entries(geo).sort((a,b)=>b[1]-a[1]).forEach(([p,c])=>{
    gg+='<div class="brow"><span class="bl">'+esc(p)+'</span><span class="bv">'+c+'</span></div>';
  });
  document.getElementById('geo-list').innerHTML=gg;
}

function exportJSON(){
  const b=new Blob([JSON.stringify(D,null,2)],{type:'application/json'});
  const a=document.createElement('a');a.href=URL.createObjectURL(b);a.download='family_tree.json';a.click();
}
function onFileSelect(e){
  const f=e.target.files[0];
  if(f){const r=new FileReader();r.onload=ev=>{
    const st=document.getElementById('import-status');
    st.className='status ok';st.textContent='File loaded. Re-import requires rebuild.';st.style.display='block';
  };r.readAsText(f);}
}

// ── Transform state ───────────────────────────────────────────────────────────
let tx = 0, ty = 0, scale = 1;
const MIN_SCALE = 0.2, MAX_SCALE = 2.5;

function applyTransform(){
  document.querySelector('.tree-wrap-inner').style.transform =
    'translate('+tx+'px,'+ty+'px) scale('+scale+')';
  document.getElementById('zoom-level').textContent = Math.round(scale*100)+'%';
}

// ── Button zoom (keeps existing toolbar buttons working) ─────────────────────
let zoomLevel = 100;
function zoomIn(){ scale = Math.min(MAX_SCALE, scale+0.1); applyTransform(); }
function zoomOut(){ scale = Math.max(MIN_SCALE, scale-0.1); applyTransform(); }
function zoomReset(){ scale=1; tx=0; ty=0; applyTransform(); }

// ── Pan + Pinch via PointerEvents ────────────────────────────────────────────
(function(){
  const wrap = document.querySelector('.tree-wrap');
  const pointers = new Map();
  let lastDist = null;
  let panStart = null;

  function midpoint(a, b){
    return { x:(a.clientX+b.clientX)/2, y:(a.clientY+b.clientY)/2 };
  }
  function dist(a, b){
    return Math.hypot(a.clientX-b.clientX, a.clientY-b.clientY);
  }

  wrap.addEventListener('pointerdown', e=>{
    pointers.set(e.pointerId, e);
    wrap.setPointerCapture(e.pointerId);
    wrap.classList.add('grabbing');
    if(pointers.size === 1){
      panStart = { x: e.clientX - tx, y: e.clientY - ty };
    }
    lastDist = null;
  });

  wrap.addEventListener('pointermove', e=>{
    pointers.set(e.pointerId, e);
    if(pointers.size === 2){
      // ── Pinch-to-zoom ──
      const pts = [...pointers.values()];
      const d = dist(pts[0], pts[1]);
      if(lastDist !== null){
        const delta = d / lastDist;
        const mid = midpoint(pts[0], pts[1]);
        const rect = wrap.getBoundingClientRect();
        // Zoom toward pinch midpoint
        const ox = mid.x - rect.left;
        const oy = mid.y - rect.top;
        const newScale = Math.min(MAX_SCALE, Math.max(MIN_SCALE, scale * delta));
        tx = ox - (ox - tx) * (newScale / scale);
        ty = oy - (oy - ty) * (newScale / scale);
        scale = newScale;
        applyTransform();
      }
      lastDist = d;
    } else if(pointers.size === 1 && panStart){
      // ── Pan ──
      tx = e.clientX - panStart.x;
      ty = e.clientY - panStart.y;
      applyTransform();
    }
  });

  function onUp(e){
    pointers.delete(e.pointerId);
    if(pointers.size < 2) lastDist = null;
    if(pointers.size === 0){
      wrap.classList.remove('grabbing');
      panStart = null;
    } else if(pointers.size === 1){
      // Restart pan anchor from remaining pointer
      const remaining = [...pointers.values()][0];
      panStart = { x: remaining.clientX - tx, y: remaining.clientY - ty };
    }
  }
  wrap.addEventListener('pointerup', onUp);
  wrap.addEventListener('pointercancel', onUp);

  // ── Mouse-wheel zoom ─────────────────────────────────────────────────────
  wrap.addEventListener('wheel', e=>{
    e.preventDefault();
    const rect = wrap.getBoundingClientRect();
    const ox = e.clientX - rect.left;
    const oy = e.clientY - rect.top;
    const delta = e.deltaY < 0 ? 1.1 : 0.9;
    const newScale = Math.min(MAX_SCALE, Math.max(MIN_SCALE, scale * delta));
    tx = ox - (ox - tx) * (newScale / scale);
    ty = oy - (oy - ty) * (newScale / scale);
    scale = newScale;
    applyTransform();
  }, { passive: false });

  // ── Double-tap to re-centre ───────────────────────────────────────────────
  let lastTap = 0;
  wrap.addEventListener('pointerdown', e=>{
    if(pointers.size > 1) return;
    const now = Date.now();
    if(now - lastTap < 300){
      scale=1; tx=0; ty=0; applyTransform();
    }
    lastTap = now;
  });
})();

// ── Collapsible search bar ────────────────────────────────────────────────────
function toggleSearch(){
  const bar = document.getElementById('search-bar');
  const isOpen = bar.classList.toggle('open');
  if(isOpen) document.getElementById('search-in').focus();
  else clearSearch();
}

// ── Auto-pan to search hit ────────────────────────────────────────────────────
function panToHit(){
  const el = document.querySelector('.search-hit');
  if(!el) return;
  const wrap = document.querySelector('.tree-wrap');
  const inner = document.querySelector('.tree-wrap-inner');
  const wRect = wrap.getBoundingClientRect();
  const eRect = el.getBoundingClientRect();
  const iRect = inner.getBoundingClientRect();
  // Element centre in inner-coordinate space
  const elCx = (eRect.left - iRect.left) / scale + (eRect.width / scale) / 2;
  const elCy = (eRect.top  - iRect.top)  / scale + (eRect.height/ scale) / 2;
  // Target: centre of wrap
  tx = wRect.width  / 2 - elCx * scale;
  ty = wRect.height / 2 - elCy * scale;
  applyTransform();
}

// ── Abbreviation toggle ───────────────────────────────────────────────────────
let showAbbr = false;

function toAbbr(name){
  // Strip Islamic honorifics: H. / Hj. at the start (case-insensitive)
  const stripped = name.replace(/^(H\.|Hj\.)\s*/i, '').trim();
  // Take first letter of each word
  return stripped.split(/\s+/).map(w => w[0] ? w[0].toUpperCase() : '').join('');
}

function toggleAbbr(){
  showAbbr = !showAbbr;
  document.getElementById('abbr-btn').style.background = showAbbr ? '#d4af37' : '#2d7d6e';
  document.getElementById('abbr-btn').style.color      = showAbbr ? '#1a1a2e' : '#d4af37';
  renderTree();
}

// ── Click/tap to toggle tooltip (for touch/smart devices) ────────────────────
function closeAllTips(){
  document.querySelectorAll('.tip.visible').forEach(t=>t.classList.remove('visible'));
}

document.addEventListener('click', function(e){
  const couple = e.target.closest('.couple');
  if(couple){
    const tip = couple.querySelector('.tip');
    if(!tip) return;
    const isVisible = tip.classList.contains('visible');
    closeAllTips();                          // close any other open tip
    if(!isVisible) tip.classList.add('visible'); // toggle open
  } else {
    closeAllTips();                          // tap outside → close all
  }
});

updateDashboard();
renderTree();
</script>
</body>
</html>'''

    out_path.write_text(html, encoding='utf-8')

# ── Main ──────────────────────────────────────────────────────────────────────


def main():
    print("Parsing CSV…")
    entries, code_order, duplicate_person_codes = parse_csv(CSV_PATH)
    print(f"  {len(entries)} entries found")
    if duplicate_person_codes:
        print(
            f"  Duplicate person codes (multi-marriage): {duplicate_person_codes}")

    persons, spouses, marriages, spouse_of, children_of, children_via = classify(
        entries, code_order, duplicate_person_codes)
    print(f"  {len(persons)} blood members, {len(spouses)} spouses")
    print(f"  {sum(1 for v in marriages.values() if len(v) > 1)} multi-marriages")

    # Debug: check for duplicates
    for p, sp_list in marriages.items():
        if len(sp_list) > 1:
            print(
                f"  Multi: {persons[p]['name']} ({p}) → {', '.join(sp_list)}")

    data = generate(persons, spouses, marriages, spouse_of,
                    children_of, children_via, entries)

    print("Writing HTML…")
    write_html(data, OUT_PATH)
    print(f"  Generated at: {datetime.now().strftime('%-d/%b/%Y %H:%M:%S')}")
    print(f"✓ Done → {OUT_PATH}")
    print(f"  Total persons in tree: {len(data['persons'])}")
    print(f"  Total spouses: {len(data['spouses'])}")


if __name__ == '__main__':
    main()
