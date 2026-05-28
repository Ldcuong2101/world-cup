# Admin Panel Redesign Plan

## Known Bugs to Fix First
- Rating input box too small (width needs to increase)
- Rating cannot be saved from the current inline form (form submission broken)
- `|tojson` → `|jsattr` fix already applied (double-quote attribute bug)

---

## New Layout: Split "Pre-Match" vs "Post-Match"

Each match card becomes a two-panel expandable card:

```
┌─────────────────────────────────────────────────────────────┐
│ [Stage] [Flag] Home — Away [Flag]    Date · Time   [Status] │
│                                                             │
│  [ PRE-MATCH ]                [ POST-MATCH ]               │
│  (tab or side-by-side)        (tab or side-by-side)        │
└─────────────────────────────────────────────────────────────┘
```

---

## PRE-MATCH Tab / Panel

Fields the admin sets **before the match kicks off**:

### 1. Match Time
- `datetime-local` input to change `match.match_date`
- Useful for reschedules
- Route: `POST /admin/match/{id}/time`

### 2. Kèo Chấp (Handicap Rating)
- Two clearly-sized number inputs: `[  1.5  ] : [  0  ]`
- Minimum input width: `w-20` (80px), font size `text-lg`
- Labels: home team name on left, away on right
- "Save Rating" button — dedicated, standalone form
- Route: `POST /admin/match/{id}/rating`  ← keep separate, fix the broken save

### 3. Win Probability Slider
- Range slider 30–70 for `home_strength_rating`
- Live display: "Mexico 57% · Draw 22% · South Africa 21%"
- "Save Probability" button (can be combined with rating save)
- Route: same as rating or `POST /admin/match/{id}/prematch`

### 4. (Optional) Media / Context
- YouTube URL input → stored as `match.youtube_url` (new field)
- Embed auto-detected from URL (show thumbnail preview if valid)
- Players to watch: free-text or tag input → stored as `match.players_note`
- Match notes / preview text → `match.preview_text`
- Route: `POST /admin/match/{id}/prematch`

---

## POST-MATCH Tab / Panel

Fields the admin sets **after the match finishes**:

### 1. Score & Result
- Large score inputs (bigger than current): `w-20 text-2xl`
- ET checkbox + ET score inputs (shown when ET checked)
- PEN checkbox + PEN score inputs (shown when PEN checked)
- Winner auto-computed from scores + rating (shown as preview before save)
- Route: `POST /admin/match/{id}/result`

### 2. Highlight / Media
- YouTube highlight URL → stored as `match.highlight_url` (new field)
- Auto-embed preview in match card on the user-facing matches page
- Route: included in `POST /admin/match/{id}/result` or separate `POST /admin/match/{id}/highlight`

### 3. (Optional) Match Stats
- Total goals, possession % (home/away), cards
- Free-text "match summary" shown in the match card
- Could be a JSON blob field on Match for flexibility

---

## Database Changes Needed

```python
class Match(Base):
    # ... existing fields ...

    # Pre-match additions
    youtube_url     = Column(String, nullable=True)   # pre-match preview video
    players_note    = Column(String, nullable=True)   # "Watch: Mbappe, Ronaldo"
    preview_text    = Column(String, nullable=True)   # short preview paragraph

    # Post-match additions
    highlight_url   = Column(String, nullable=True)   # YouTube highlight link
    match_summary   = Column(String, nullable=True)   # brief match recap text
```

---

## UI Structure (Alpine.js)

```
<div x-data="{ panel: 'pre' }">   <!-- per match card -->

  <!-- Panel toggle -->
  <div class="flex border-b ...">
    <button @click="panel='pre'"  :class="panel==='pre' ? 'active' : ''">⏱ Pre-Match</button>
    <button @click="panel='post'" :class="panel==='post' ? 'active' : ''">🏁 Post-Match</button>
  </div>

  <!-- PRE-MATCH panel -->
  <div x-show="panel==='pre'">
    <!-- time, rating, probability, media -->
  </div>

  <!-- POST-MATCH panel -->
  <div x-show="panel==='post'">
    <!-- scores, ET/PEN, highlight URL -->
  </div>

</div>
```

---

## Route Map

| Route | Method | Purpose |
|---|---|---|
| `/admin/match/{id}/time` | POST | Update match kickoff time |
| `/admin/match/{id}/rating` | POST | Save rating_home, rating_away |
| `/admin/match/{id}/prematch` | POST | Save strength, youtube_url, players_note, preview_text |
| `/admin/match/{id}/result` | POST | Save scores, ET/PEN, compute winner |
| `/admin/match/{id}/highlight` | POST | Save highlight_url, match_summary |

---

## User-Facing Changes (matches.html / predict.html)

- Show YouTube embed / thumbnail on match card if `match.youtube_url` set (pre-match)
- Show highlight embed on past match card if `match.highlight_url` set (post-match)
- Show `players_note` as a small badge row under team names in predict.html
- Show `match_summary` in the result card footer for completed matches

---

## Implementation Order

1. **Fix current bugs**: rating box size, rating save broken
2. **Add DB fields**: `youtube_url`, `players_note`, `preview_text`, `highlight_url`, `match_summary`
3. **Run migration** (re-seed or ALTER TABLE)
4. **Rewrite admin card** with Pre/Post tab layout
5. **Add new routes** (`/time`, `/prematch`, `/highlight`)
6. **Update user-facing templates** to show new media fields
