"""Build per-season JSON for the Spencer Family Edition NFL app.

Sources: nflverse schedules + play-by-play (1999+), FiveThirtyEight game file (1996-98),
nflverse team colors/logos and players.
"""
import json, math, os, re, sys, zlib
from collections import defaultdict
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, 'out')
SEASONS = [int(x) for x in sys.argv[2].split(',')] if len(sys.argv) > 2 else list(range(1996, 2027))
os.makedirs(OUT, exist_ok=True)

# ---------------------------------------------------------------- reference data
TEAMS = pd.read_csv(os.path.join(HERE, 'teams_colors_logos.csv')).set_index('team_abbr')
PLAYERS = pd.read_csv(os.path.join(HERE, 'players.csv'), usecols=['gsis_id', 'display_name', 'position'], low_memory=False)
PNAME = dict(zip(PLAYERS.gsis_id, PLAYERS.display_name))
PPOS = dict(zip(PLAYERS.gsis_id, PLAYERS.position))
GAMES = pd.read_csv(os.path.join(HERE, 'games.csv'), low_memory=False)

SB_MVP = {1996: 'Desmond Howard', 1997: 'Terrell Davis', 1998: 'John Elway', 1999: 'Kurt Warner', 2000: 'Ray Lewis',
          2001: 'Tom Brady', 2002: 'Dexter Jackson', 2003: 'Tom Brady', 2004: 'Deion Branch', 2005: 'Hines Ward',
          2006: 'Peyton Manning', 2007: 'Eli Manning', 2008: 'Santonio Holmes', 2009: 'Drew Brees', 2010: 'Aaron Rodgers',
          2011: 'Eli Manning', 2012: 'Joe Flacco', 2013: 'Malcolm Smith', 2014: 'Tom Brady', 2015: 'Von Miller',
          2016: 'Tom Brady', 2017: 'Nick Foles', 2018: 'Julian Edelman', 2019: 'Patrick Mahomes', 2020: 'Tom Brady',
          2021: 'Cooper Kupp', 2022: 'Patrick Mahomes', 2023: 'Patrick Mahomes', 2024: 'Jalen Hurts',
          2025: 'Kenneth Walker III'}
SB_MVP_TEAM = {1996: 'GB', 1997: 'DEN', 1998: 'DEN'}


def roman(n):
    if n == 50:
        return '50'
    vals = [(50, 'L'), (40, 'XL'), (10, 'X'), (9, 'IX'), (5, 'V'), (4, 'IV'), (1, 'I')]
    out = ''
    for v, s in vals:
        while n >= v:
            out += s
            n -= v
    return out


def sb_name(season):
    return 'Super Bowl ' + roman(season - 1965)


def team_meta(abbr, season):
    """[city, nickname, color, color2, logo, conf] as the team was known that season."""
    key = abbr
    over = {}
    if abbr == 'WAS':
        over = {'nick': 'Redskins'} if season <= 2019 else {'nick': 'Football Team'} if season <= 2021 else {}
    if abbr == 'TEN' and season <= 1998:
        over = {'city': 'Houston' if season == 1996 else 'Tennessee', 'nick': 'Oilers', 'logo': '',
                'c1': '#4F91CD', 'c2': '#D50A0A'}
    r = TEAMS.loc[key]
    name = r.team_name
    nick = r.team_nick
    city = name[: -len(nick)].strip()
    logo = str(r.team_logo_espn).replace('/500-dark/', '/500/')
    conf = r.team_conf
    if abbr == 'SEA' and season <= 2001:
        conf = 'AFC'
    return [over.get('city', city), over.get('nick', nick), over.get('c1', r.team_color),
            over.get('c2', r.team_color2), over.get('logo', logo), conf]


# ---------------------------------------------------------------- helpers
def nm(pid, fallback=None):
    if isinstance(pid, str) and pid in PNAME and isinstance(PNAME[pid], str):
        return PNAME[pid]
    if isinstance(fallback, str) and fallback:
        return fallback.replace('.', '. ').replace('  ', ' ')
    return None


def num(x, d=0):
    try:
        if x is None or (isinstance(x, float) and math.isnan(x)):
            return d
        return x
    except Exception:
        return d


def ival(x):
    return int(round(num(x, 0)))


def rec_str(w, l, t):
    return f'{w}-{l}-{t}' if t else f'{w}-{l}'


def pick(seq, key):
    """Deterministic 'random' choice so rebuilds are stable."""
    return seq[zlib.crc32(key.encode()) % len(seq)]


def clean_desc(d):
    d = re.sub(r'^\(\d+:\d+\)\s*', '', str(d))
    d = re.sub(r'\((Shotgun|No Huddle|No Huddle, Shotgun|Punt formation|Field Goal formation|Run formation)\)\s*', '', d)
    d = re.sub(r'\b\d{1,2}-(?=[A-Z])', '', d)
    d = re.sub(r'\[.*?\]', '', d)
    d = re.sub(r'\s+', ' ', d).strip()
    return d[:220]


def art(n):
    """'a' or 'an' before a spoken number (an 8-yard, an 11-yard, an 80-yard)."""
    n = int(n)
    return 'an' if (n == 8 or n == 11 or n == 18 or 80 <= n <= 89) else 'a'


def poss(n):
    return n + ("'" if n.endswith('s') else "'s")


def ordinal(n):
    return f'{n}{"tsnrhtdd"[(n // 10 % 10 != 1) * (n % 10 < 4) * n % 10::4]}'


NUMW = {2: 'two', 3: 'three', 4: 'four', 5: 'five', 6: 'six', 7: 'seven', 8: 'eight', 9: 'nine', 10: 'ten',
        11: 'eleven', 12: 'twelve', 13: 'thirteen', 14: 'fourteen', 15: 'fifteen', 16: 'sixteen'}


def nword(n):
    return NUMW.get(n, str(n))


def clock(r):
    q = ival(r.get('qtr'))
    t = r.get('time') if isinstance(r.get('time'), str) else ''
    return ('OT' if q >= 5 else f'Q{q}'), t


# ---------------------------------------------------------------- play descriptions
def play_info(r, season, nick):
    """Return dict with sentence, phrase (possessive-ish), main player, yt query, kind."""
    pos, dfn = r.get('posteam'), r.get('defteam')
    yds = ival(r.get('yards_gained'))
    passer = nm(r.get('passer_player_id'), r.get('passer_player_name'))
    recv = nm(r.get('receiver_player_id'), r.get('receiver_player_name'))
    rush = nm(r.get('rusher_player_id'), r.get('rusher_player_name'))
    kick = nm(r.get('kicker_player_id'), r.get('kicker_player_name'))
    pick6 = nm(r.get('interception_player_id'), r.get('interception_player_name'))
    sacker = nm(r.get('sack_player_id'), r.get('sack_player_name')) or nm(r.get('half_sack_1_player_id'), r.get('half_sack_1_player_name'))
    opp_of = lambda t: nick.get(t, t)
    td = num(r.get('touchdown')) == 1
    down = ival(r.get('down'))
    togo = ival(r.get('ydstogo'))
    conv = f' on 4th-and-{togo}' if down == 4 and num(r.get('fourth_down_converted')) == 1 else ''
    if num(r.get('field_goal_attempt')) == 1:
        dist = ival(r.get('kick_distance'))
        res = r.get('field_goal_result')
        k = kick or nick.get(pos, pos) + ' kicker'
        if res == 'made':
            return dict(kind='fg', who=k, s=f'{k} nails {art(dist)} {dist}-yard field goal.', ph=f"{poss(k)} {dist}-yard field goal",
                        q=f'{k} {dist} yard field goal {opp_of(dfn)} {season}')
        verb = f'has {art(dist)}' if res == 'blocked' else f'misses {art(dist)}'
        tail = ' blocked' if res == 'blocked' else ''
        return dict(kind='fgx', who=k, s=f'{k} {verb} {dist}-yard field goal try{tail}.', ph=f"a {'blocked' if res=='blocked' else 'missed'} {dist}-yard field goal",
                    q=f'{k} missed field goal {opp_of(pos if res else dfn)} {season}')
    if td and num(r.get('return_touchdown')) == 1:
        ry = ival(r.get('return_yards'))
        if num(r.get('interception')) == 1 and pick6:
            return dict(kind='pick6', who=pick6, s=f'{pick6} picks off {passer or "the pass"} and takes it {ry} yards for a touchdown.',
                        ph=f"{poss(pick6)} {ry}-yard pick-six", q=f'{pick6} pick six {opp_of(pos)} {season}')
        pt = r.get('play_type')
        retn = nm(r.get('punt_returner_player_id'), r.get('punt_returner_player_name')) if pt == 'punt' else \
            nm(r.get('kickoff_returner_player_id'), r.get('kickoff_returner_player_name')) if pt == 'kickoff' else \
            nm(r.get('td_player_id'), r.get('td_player_name'))
        what = 'punt' if pt == 'punt' else 'kickoff' if pt == 'kickoff' else 'fumble'
        retn = retn or nick.get(r.get('td_team'), '')
        return dict(kind='rettd', who=retn, s=f'{retn} returns a {what} {ry} yards for a touchdown.',
                    ph=f"{poss(retn)} {ry}-yard {what}-return touchdown", q=f'{retn} {what} return touchdown {season}')
    if num(r.get('interception')) == 1 and pick6:
        return dict(kind='int', who=pick6, s=f'{pick6} intercepts {passer or "the pass"}.', ph=f"{poss(pick6)} interception",
                    q=f'{pick6} interception {opp_of(pos)} {season}')
    if num(r.get('sack')) == 1 and sacker:
        ff = ' and forces a fumble' if num(r.get('fumble_lost')) == 1 else ''
        return dict(kind='sack', who=sacker, s=f'{sacker} sacks {passer or "the quarterback"}{ff}.', ph=f"{poss(sacker)} sack",
                    q=f'{sacker} sack {opp_of(pos)} {season}')
    if num(r.get('fumble_lost')) == 1:
        fr = nm(r.get('fumble_recovery_1_player_id'), r.get('fumble_recovery_1_player_name'))
        who = nm(r.get('forced_fumble_player_1_player_id'), r.get('forced_fumble_player_1_player_name')) or fr
        s = f'{who} forces a fumble' if who else f'The {nick.get(dfn, dfn)} force a fumble'
        s += f' and {fr} recovers.' if fr and fr != who else ' and recover.'
        return dict(kind='fum', who=who or fr or '', s=s, ph=f"a forced fumble by {who}" if who else 'a fumble recovery',
                    q=f'{who or nick.get(dfn, dfn)} forced fumble {opp_of(pos)} {season}')
    if r.get('play_type') == 'pass' and passer and recv and num(r.get('complete_pass')) == 1:
        if td:
            return dict(kind='passtd', who=passer, s=f'{passer} hits {recv} for {art(yds)} {yds}-yard touchdown{conv}.',
                        ph=f"{poss(passer)} {yds}-yard TD pass to {recv}", q=f'{passer} {recv} {yds} yard touchdown {opp_of(dfn)} {season}')
        return dict(kind='pass', who=recv, s=f'{passer} connects with {recv} for {yds} yards{conv}.',
                    ph=f"{poss(passer)} {yds}-yard strike to {recv}", q=f'{passer} to {recv} {yds} yards {opp_of(dfn)} {season}')
    if r.get('play_type') == 'run' and rush:
        if td:
            s = f'{rush} punches it in from {yds} yard{"s" if yds != 1 else ""} out{conv}.' if yds <= 5 else f'{rush} breaks free for {art(yds)} {yds}-yard touchdown run{conv}.'
            return dict(kind='rushtd', who=rush, s=s, ph=f"{poss(rush)} {yds}-yard TD run", q=f'{rush} {yds} yard touchdown run {opp_of(dfn)} {season}')
        if down == 4 and num(r.get('fourth_down_failed')) == 1:
            return dict(kind='stop', who='', s=f'The {nick.get(dfn, dfn)} stuff {rush} on 4th-and-{togo}.', ph='a fourth-down stop',
                        q=f'{nick.get(dfn, dfn)} fourth down stop {nick.get(pos, pos)} {season}')
        return dict(kind='run', who=rush, s=f'{rush} rips off {art(yds)} {yds}-yard run{conv}.', ph=f"{poss(rush)} {yds}-yard run",
                    q=f'{rush} {yds} yard run {opp_of(dfn)} {season}')
    if r.get('play_type') == 'pass' and down == 4 and num(r.get('fourth_down_failed')) == 1:
        return dict(kind='stop', who='', s=f'The {nick.get(dfn, dfn)} stop {passer or "the offense"} on 4th-and-{togo}.', ph='a fourth-down stop',
                    q=f'{nick.get(dfn, dfn)} fourth down stop {nick.get(pos, pos)} {season}')
    if num(r.get('safety')) == 1:
        return dict(kind='safety', who='', s=f'The {nick.get(dfn, dfn)} record a safety.', ph='a safety', q=f'{nick.get(dfn, dfn)} safety {season}')
    d = clean_desc(r.get('desc'))
    return dict(kind='other', who='', s=d, ph='a big play', q=f'{nick.get(pos, pos)} vs {nick.get(dfn, dfn)} {season} highlights')


# ---------------------------------------------------------------- player stats & MVP
def player_stats(p):
    st = defaultdict(lambda: defaultdict(float))
    team = {}
    credit = defaultdict(float)

    def add(pid, k, v, t=None):
        if isinstance(pid, str):
            st[pid][k] += v
            if t and pid not in team:
                team[pid] = t

    for r in p.to_dict('records'):
        pos, dfn = r.get('posteam'), r.get('defteam')
        w = num(r.get('wpa'), 0.0)
        if num(r.get('two_point_attempt')) == 1 or r.get('play_type') in ('no_play', 'qb_kneel', 'qb_spike', None):
            if r.get('play_type') != 'no_play':
                continue
            if num(r.get('penalty')) == 1:
                continue
        pas, rec, rus = r.get('passer_player_id'), r.get('receiver_player_id'), r.get('rusher_player_id')
        if isinstance(pas, str):
            comp = num(r.get('complete_pass')) == 1
            att = comp or num(r.get('incomplete_pass')) == 1 or num(r.get('interception')) == 1
            if att:
                add(pas, 'att', 1, pos)
            if comp:
                add(pas, 'cmp', 1, pos)
                add(pas, 'pyd', num(r.get('passing_yards')), pos)
            if num(r.get('pass_touchdown')) == 1:
                add(pas, 'ptd', 1, pos)
            if num(r.get('interception')) == 1:
                add(pas, 'int', 1, pos)
            credit[pas] += (0.6 if comp else 1.0) * w
        if isinstance(rec, str) and num(r.get('complete_pass')) == 1:
            add(rec, 'rec', 1, pos)
            add(rec, 'ryd', num(r.get('receiving_yards')), pos)
            if num(r.get('pass_touchdown')) == 1:
                add(rec, 'rtd', 1, pos)
            credit[rec] += 0.6 * w
        if isinstance(rus, str) and r.get('play_type') == 'run':
            add(rus, 'car', 1, pos)
            add(rus, 'uyd', num(r.get('rushing_yards')), pos)
            if num(r.get('rush_touchdown')) == 1:
                add(rus, 'utd', 1, pos)
            credit[rus] += w
        if num(r.get('sack')) == 1:
            s1 = r.get('sack_player_id')
            if isinstance(s1, str):
                add(s1, 'sk', 1, dfn); credit[s1] -= w
            for h in ('half_sack_1_player_id', 'half_sack_2_player_id'):
                if isinstance(r.get(h), str):
                    add(r.get(h), 'sk', 0.5, dfn); credit[r.get(h)] -= w / 2
        ip = r.get('interception_player_id')
        if num(r.get('interception')) == 1 and isinstance(ip, str):
            add(ip, 'dint', 1, dfn); credit[ip] -= w
        ff = r.get('forced_fumble_player_1_player_id')
        if num(r.get('fumble_lost')) == 1 and isinstance(ff, str):
            add(ff, 'ff', 1, dfn); credit[ff] -= w
        fr = r.get('fumble_recovery_1_player_id')
        if num(r.get('fumble_lost')) == 1 and isinstance(fr, str) and r.get('fumble_recovery_1_team') == dfn:
            add(fr, 'fr', 1, dfn); credit[fr] -= w * 0.5
        if num(r.get('return_touchdown')) == 1 and isinstance(r.get('td_player_id'), str):
            add(r.get('td_player_id'), 'rettd', 1, r.get('td_team'))
            credit[r.get('td_player_id')] += abs(w)
        if num(r.get('field_goal_attempt')) == 1 and isinstance(r.get('kicker_player_id'), str):
            k = r.get('kicker_player_id')
            add(k, 'fga', 1, pos)
            if r.get('field_goal_result') == 'made':
                add(k, 'fgm', 1, pos)
                st[k]['fglong'] = max(st[k]['fglong'], num(r.get('kick_distance')))
            credit[k] += w
    return st, team, credit


def fantasy(s):
    return (s['pyd'] * 0.04 + s['ptd'] * 4 - s['int'] * 2 + s['uyd'] * 0.1 + s['utd'] * 6 + s['rec'] * 0.5 +
            s['ryd'] * 0.1 + s['rtd'] * 6 + s['sk'] * 3 + s['dint'] * 5 + s['ff'] * 3 + s['fr'] * 2 + s['rettd'] * 6 +
            s['fgm'] * 3 + (1 if s['fglong'] >= 50 else 0) - (s['fga'] - s['fgm']))


def stat_line(s):
    parts = []
    if s['att'] >= 5:
        x = f"{int(s['cmp'])}/{int(s['att'])}, {int(s['pyd'])} yds"
        if s['ptd']: x += f", {int(s['ptd'])} TD"
        if s['int']: x += f", {int(s['int'])} INT"
        parts.append(x)
    if s['car'] >= 5 or s['uyd'] >= 40 or s['utd']:
        x = f"{int(s['car'])} car, {int(s['uyd'])} rush yds"
        if s['utd']: x += f", {int(s['utd'])} TD"
        parts.append(x)
    if s['rec'] >= 2 or s['ryd'] >= 40 or s['rtd']:
        x = f"{int(s['rec'])} rec, {int(s['ryd'])} yds"
        if s['rtd']: x += f", {int(s['rtd'])} TD"
        parts.append(x)
    d = []
    if s['sk']: d.append(f"{s['sk']:g} sack{'s' if s['sk'] != 1 else ''}")
    if s['dint']: d.append(f"{int(s['dint'])} INT")
    if s['ff']: d.append(f"{int(s['ff'])} FF")
    if s['fr']: d.append(f"{int(s['fr'])} FR")
    if d: parts.append(', '.join(d))
    if s['rettd']: parts.append(f"{int(s['rettd'])} return TD")
    if s['fga']:
        x = f"{int(s['fgm'])}/{int(s['fga'])} FG"
        if s['fgm']: x += f", long {int(s['fglong'])}"
        parts.append(x)
    return ' · '.join(parts[:3])


def short_pos(pid, s):
    p = PPOS.get(pid)
    if isinstance(p, str):
        return p
    if s['att'] >= 5: return 'QB'
    if s['car'] >= 5: return 'RB'
    if s['rec'] >= 1: return 'WR'
    if s['fga']: return 'K'
    return 'DEF'


# ---------------------------------------------------------------- game story
def blurb(g, ctx, nick, season, facts):
    """Compose a 1-3 sentence story from facts. g: dict with a,h,as,hs,type; ctx: records/streaks."""
    a, h, sa, sh = g['a'], g['h'], g['as'], g['hs']
    key = g['id']
    if sa == sh:
        s = f"The {nick[a]} and {nick[h]} battled to a {sa}-{sh} tie"
        s += ' after overtime.' if g.get('ot') else '.'
        extra = []
        if facts.get('mvp_note'): extra.append(facts['mvp_note'])
        return ' '.join([s] + extra[:1])
    W, L = (h, a) if sh > sa else (a, h)
    ws, ls = max(sa, sh), min(sa, sh)
    Wn, Ln = nick[W], nick[L]
    score = f'{ws}-{ls}'
    margin = ws - ls
    gt = g['t']
    used = set()
    lead = None
    # ---- headline
    if gt == 'SB':
        lead = f"The {Wn} won {sb_name(season)}, beating the {Ln} {score}"
        lead += ' in overtime.' if g.get('ot') else '.'
        used.add('playoff')
    elif gt == 'CON':
        conf = facts['conf']
        lead = f"The {Wn} beat the {Ln} {score} to win the {conf} title and punch their ticket to {sb_name(season)}."
        used.add('playoff')
    elif gt in ('WC', 'DIV'):
        nxt = 'the Divisional Round' if gt == 'WC' else f"the {facts['conf']} Championship"
        v = pick(['knocked out', 'eliminated', 'ended the season for'], key)
        lead = f"The {Wn} {v} the {Ln} {score} to advance to {nxt}."
        used.add('playoff')
    if facts.get('late') and facts.get('deficit', 0) >= 10:
        late_txt = 'in overtime' if facts['late_ot'] else f"with {facts['late_clock']} left"
        s2 = f"They erased {art(facts['deficit'])} {facts['deficit']}-point deficit and won it on {facts['late_play']} {late_txt}."
        if lead: lead += ' ' + s2
        else: lead = f"The {Wn} erased {art(facts['deficit'])} {facts['deficit']}-point deficit to beat the {Ln} {score}, winning it on {facts['late_play']} {late_txt}."
        used |= {'late', 'comeback'}
    elif facts.get('late'):
        late_txt = 'in overtime' if facts['late_ot'] else f"with {facts['late_clock']} left"
        if lead: lead += f" {facts['late_play'][0].upper() + facts['late_play'][1:]} {late_txt} decided it."
        else: lead = f"The {Wn} {pick(['beat', 'edged', 'stunned'] if margin <= 3 else ['beat', 'got past'], key)} the {Ln} {score} on {facts['late_play']} {late_txt}."
        used.add('late')
    elif facts.get('deficit', 0) >= 14:
        s2 = f"rallied from {facts['deficit']} points down"
        if lead: lead += f" They {s2} to do it."
        else: lead = f"The {Wn} {s2} to beat the {Ln} {score}."
        used.add('comeback')
    if not lead and ctx['Lstreak'] >= 5 and ctx['Lpre'][1] == 0:
        lead = f"The {Wn} handed the previously unbeaten {Ln} their first loss of the season, {score}."
        used.add('Lstreak')
    if not lead and facts.get('dog', 0) >= 7:
        lead = f"The {Wn} stunned the {Ln} {score} as {facts['dog']:g}-point underdogs."
        used.add('upset')
    if not lead and facts.get('elo_upset'):
        lead = f"The {Wn} pulled off an upset of the {Ln}, {score}."
        used.add('upset')
    if not lead and ctx['Lstreak'] >= 5:
        lead = f"The {Wn} snapped the {Ln}' {ctx['Lstreak']}-game winning streak with a {score} win."
        used.add('Lstreak')
    if not lead and ctx['Wstreak'] <= -3:
        lead = f"The {Wn} snapped {art(-ctx['Wstreak'])} {-ctx['Wstreak']}-game losing streak by beating the {Ln} {score}."
        used.add('Wstreak')
    if not lead and ctx['Wpre'][0] == 0 and ctx['Wpre'][1] >= 2 and gt == 'REG':
        lead = f"The {Wn} finally got their first win of the season, beating the {Ln} {score}."
        used.add('first')
    if not lead and ls == 0:
        lead = f"The {Wn} shut out the {Ln}, {score}."
        used.add('shutout')
    if not lead and margin >= 28:
        lead = f"The {Wn} {pick(['routed', 'crushed', 'blew out', 'dominated'], key)} the {Ln} {score}."
        used.add('blowout')
    if not lead and ws + ls >= 70:
        lead = f"The {Wn} outlasted the {Ln} {score} in a shootout."
        used.add('shootout')
    if not lead and facts.get('dog', 0) >= 3.5:
        lead = f"The {Wn} upset the {Ln} {score} as {facts['dog']:g}-point underdogs."
        used.add('upset')
    if not lead and facts.get('q4comeback'):
        lead = f"The {Wn} rallied in the fourth quarter to beat the {Ln} {score}."
        used.add('q4')
    if not lead:
        v = 'outlasted' if g.get('ot') else pick(['edged', 'held off', 'slipped past'], key) if margin <= 3 else \
            pick(['handled', 'took care of', 'cruised past'], key) if margin >= 17 else pick(['beat', 'topped', 'defeated'], key)
        lead = f"The {Wn} {v} the {Ln} {score}" + (' in overtime.' if g.get('ot') and v != 'outlasted' else ' in overtime.' if g.get('ot') else '.')
    # ---- supporting facts
    extra = []
    if facts.get('mvp_note'):
        extra.append(facts['mvp_note'])
    if gt == 'REG':
        wr = rec_str(*ctx['Wpost'])
        lr = rec_str(*ctx['Lpost'])
        if 'Lstreak' not in used and ctx['Lstreak'] >= 4:
            extra.append(f"It ended the {Ln}' {ctx['Lstreak']}-game winning streak.")
        elif 'Lstreak' in used and 'upset' not in used and (facts.get('dog', 0) >= 3.5 or facts.get('elo_upset')):
            extra.append(f"They did it as {facts['dog']:g}-point underdogs." if facts.get('dog') else "Few saw the upset coming.")
        elif 'Wstreak' not in used and ctx['Wstreak'] <= -3:
            extra.append(f"It snapped {art(-ctx['Wstreak'])} {-ctx['Wstreak']}-game skid for the {Wn}.")
        if ctx['Wpost'][1] == 0 and ctx['Wpost'][2] == 0 and ctx['Wpost'][0] >= 5:
            extra.append(f"The {Wn} stayed perfect at {wr}.")
        elif ctx['Wstreak'] >= 3:
            extra.append(f"It was their {ordinal(ctx['Wstreak'] + 1)} straight win, improving to {wr}.")
        elif ctx['Lpost'][0] == 0 and ctx['Lpost'][1] >= 5:
            extra.append(f"The {Ln} fell to {lr}.")
        elif facts.get('final_week'):
            extra.append(f"The {Wn} finished the regular season {wr}.")
        elif facts.get('div') and ctx['Wpost'][0] >= ctx['Wpost'][1] + 3 and g['wk'] >= 12:
            extra.append(f"The division win pushed them to {wr} down the stretch.")
        elif 'upset' not in used and facts.get('dog', 0) >= 3.5:
            extra.append(f"They pulled it off as {facts['dog']:g}-point underdogs.")
    elif 'upset' not in used and facts.get('dog', 0) >= 5:
        extra.append(f"They did it as {facts['dog']:g}-point underdogs.")
    if gt == 'SB' and facts.get('sbmvp'):
        extra.append(f"{facts['sbmvp']} was named Super Bowl MVP.")
    return ' '.join([lead] + extra[:2])


# ---------------------------------------------------------------- per game analysis from pbp
def analyze(g, p, season, nick):
    """Return facts, mvp, plays for one game using play-by-play rows p."""
    facts = {}
    a, h = g['a'], g['h']
    p = p.reset_index(drop=True)
    alias = {}
    if len(p):
        alias = {p['home_team'].iloc[0]: h, p['away_team'].iloc[0]: a}
        cols = ['posteam', 'defteam', 'td_team', 'fumble_recovery_1_team', 'return_team']
        for c in cols:
            if c in p:
                p[c] = p[c].map(lambda v: alias.get(v, v))
    hs = p['total_home_score'].ffill().fillna(0).astype(int)
    as_ = p['total_away_score'].ffill().fillna(0).astype(int)
    if g['hs'] == g['as']:
        W = None
    else:
        W = h if g['hs'] > g['as'] else a
    lead_w = (hs - as_) if W == h else (as_ - hs)
    # comeback size
    if W:
        facts['deficit'] = int(max(0, -lead_w.min()))
        # Q4 comeback: trailing at some point in the 4th
        q = p['qtr'].fillna(0).astype(int)
        facts['q4comeback'] = bool(((q >= 4) & (lead_w < 0)).any())
        # last go-ahead-for-good play
        prev = lead_w.shift(1).fillna(0)
        idx = None
        for i in range(len(p) - 1, -1, -1):
            if lead_w.iloc[i] > 0 and prev.iloc[i] <= 0:
                if (lead_w.iloc[i:] > 0).all():
                    idx = i
                break
        decisive = None
        if idx is not None:
            r = p.iloc[idx]
            # extra point / 2pt that took the lead -> credit the touchdown before it
            if r.get('play_type') == 'extra_point' or num(r.get('two_point_attempt')) == 1:
                for j in range(idx - 1, max(idx - 6, -1), -1):
                    if num(p.iloc[j].get('touchdown')) == 1:
                        r = p.iloc[j]
                        break
            decisive = r
            gsr = num(r.get('game_seconds_remaining'), 9999)
            qq = ival(r.get('qtr'))
            if qq >= 5 or (qq == 4 and gsr <= 120):
                info = play_info(r.to_dict(), season, nick)
                facts['late'] = True
                facts['late_ot'] = qq >= 5
                facts['late_clock'] = r.get('time') if isinstance(r.get('time'), str) else ''
                if facts['late_clock'].startswith('00:'):
                    facts['late_clock'] = '0:' + facts['late_clock'][3:]
                elif facts['late_clock'].startswith('0') and len(facts['late_clock']) == 5:
                    facts['late_clock'] = facts['late_clock'][1:]
                facts['late_play'] = info['ph']
        facts['decisive_idx'] = None if decisive is None else int(decisive.name)
    # player stats / MVP
    st, team, credit = player_stats(p)
    score = {pid: fantasy(s) + 25 * credit.get(pid, 0) for pid, s in st.items()}
    mvp = None
    pool = [pid for pid in score if (W is None or team.get(pid) == W)]
    if g['t'] == 'SB' and season in SB_MVP:
        target = SB_MVP[season]
        cand = [pid for pid in st if PNAME.get(pid) == target]
        if cand:
            pid = cand[0]
            mvp = dict(n=target, tm=team.get(pid, W), pos=short_pos(pid, st[pid]), l=stat_line(st[pid]), off=1)
        else:
            mvp = dict(n=target, tm=W, pos='', l='', off=1)
    elif pool:
        pid = max(pool, key=lambda k: score[k])
        if score[pid] >= 6:
            s = st[pid]
            mvp = dict(n=nm(pid) or pid, tm=team.get(pid, W), pos=short_pos(pid, s), l=stat_line(s))
            # milestone note for the story
            nmv = mvp['n']
            if s['pyd'] >= 400:
                facts['mvp_note'] = f"{nmv} threw for {int(s['pyd'])} yards" + (f" and {int(s['ptd'])} touchdowns." if s['ptd'] >= 2 else '.')
            elif s['ptd'] >= 5:
                facts['mvp_note'] = f"{nmv} threw {int(s['ptd'])} touchdown passes."
            elif s['uyd'] >= 175:
                facts['mvp_note'] = f"{nmv} ran for {int(s['uyd'])} yards" + (f" and {int(s['utd'])} scores." if s['utd'] >= 2 else '.')
            elif s['ryd'] >= 175:
                facts['mvp_note'] = f"{nmv} piled up {int(s['ryd'])} receiving yards" + (f" and {int(s['rtd'])} touchdowns." if s['rtd'] >= 2 else '.')
            elif s['utd'] + s['rtd'] >= 3:
                facts['mvp_note'] = f"{nmv} scored {nword(int(s['utd'] + s['rtd']))} touchdowns."
            elif s['sk'] >= 3:
                facts['mvp_note'] = f"{nmv} wrecked the game with {s['sk']:g} sacks."
            elif s['dint'] >= 2:
                facts['mvp_note'] = f"{nmv} came up with {int(s['dint'])} interceptions."
    # big plays
    cands = []
    for i, r in p.iterrows():
        pt = r.get('play_type')
        if pt in ('extra_point', 'qb_kneel', 'qb_spike', 'no_play') or not isinstance(pt, str):
            continue
        if num(r.get('two_point_attempt')) == 1:
            continue
        if pt in ('kickoff', 'punt') and not (num(r.get('touchdown')) == 1 or num(r.get('fumble_lost')) == 1 or num(r.get('punt_blocked')) == 1):
            continue
        if num(r.get('game_seconds_remaining'), 0) >= 3600 and num(r.get('touchdown')) != 1:
            continue
        w = abs(num(r.get('wpa'), 0.0))
        sc = w * 100
        yds = ival(r.get('yards_gained'))
        if num(r.get('touchdown')) == 1 and yds >= 50: sc += 12
        if num(r.get('return_touchdown')) == 1: sc += 15
        if facts.get('decisive_idx') is not None and i == facts['decisive_idx']: sc += 25
        if sc < 8:
            continue
        cands.append((sc, i, r))
    cands.sort(key=lambda x: -x[0])
    chosen = sorted(cands[:3], key=lambda x: x[1])
    plays = []
    for sc, i, r in chosen:
        info = play_info(r.to_dict(), season, nick)
        if info['kind'] == 'other' and sc < 20:
            continue
        ql, t = clock(r.to_dict())
        t = (t or '').lstrip('0') or '0:00'
        if t.startswith(':'): t = '0' + t
        tag = ''
        if facts.get('decisive_idx') is not None and i == facts['decisive_idx']:
            tag = 'GAME-WINNER' if facts.get('late') else 'GO-AHEAD'
        plays.append(dict(q=ql, c=t, x=info['s'], y=info['q'], g=tag))
    return facts, mvp, plays


# ---------------------------------------------------------------- season assembly
def season_games(season):
    if season >= 1999:
        df = GAMES[GAMES.season == season].copy()
        rows = []
        for r in df.itertuples():
            rows.append(dict(id=r.game_id, t=r.game_type, wk=int(r.week), d=r.gameday, tm=r.gametime if isinstance(r.gametime, str) else '',
                             a=r.away_team, h=r.home_team,
                             as_=None if pd.isna(r.away_score) else int(r.away_score),
                             hs=None if pd.isna(r.home_score) else int(r.home_score),
                             ot=int(num(r.overtime)), n=1 if r.location == 'Neutral' else 0,
                             spread=None if pd.isna(r.spread_line) else float(r.spread_line),
                             div=int(num(r.div_game)), espn=None if pd.isna(r.espn) else str(int(float(r.espn))), elo=None))
        return rows
    d = pd.read_csv(os.path.join(HERE, 'elo/data/nfl_games.csv'))
    d = d[d.season == season].copy()
    d['date'] = pd.to_datetime(d.date)
    first = d.date.min()
    anchor = first - pd.Timedelta(days=(first.weekday() - 1) % 7)  # Tuesday on/before first game
    d['wk'] = ((d.date - anchor).dt.days // 7 + 1).astype(int)
    fix = {'LAC': 'SD', 'LAR': 'STL', 'WSH': 'WAS'}
    pw = sorted(d[d.playoff == 1].wk.unique())
    rnd = {w: ['WC', 'DIV', 'CON', 'SB'][min(i, 3)] for i, w in enumerate(pw)}
    rows = []
    for r in d.itertuples():
        h, a = fix.get(r.team1, r.team1), fix.get(r.team2, r.team2)
        t = rnd[r.wk] if r.playoff == 1 else 'REG'
        wk = r.wk if t == 'REG' else {'WC': 18, 'DIV': 19, 'CON': 20, 'SB': 21}[t]
        rows.append(dict(id=f'{season}_{r.wk:02d}_{a}_{h}', t=t, wk=int(wk), d=r.date.strftime('%Y-%m-%d'), tm='',
                         a=a, h=h, as_=int(r.score2), hs=int(r.score1), ot=0, n=int(r.neutral), spread=None, div=0, espn=None,
                         elo=float(r.elo_prob1)))
    return rows


def build(season):
    rows = season_games(season)
    rows.sort(key=lambda r: (r['d'], r['tm'], r['id']))
    abbrs = sorted({r['a'] for r in rows} | {r['h'] for r in rows})
    teams = {t: team_meta(t, season) for t in abbrs}
    nick = {t: teams[t][1] for t in abbrs}
    conf = {t: teams[t][5] for t in abbrs}
    pbp = None
    pf = os.path.join(HERE, 'pbp', f'play_by_play_{season}.csv.gz')
    if os.path.exists(pf):
        pbp = pd.read_csv(pf, low_memory=False)
        pbp = {k: v for k, v in pbp.groupby('game_id', sort=False)}
    rec = defaultdict(lambda: [0, 0, 0])
    streak = defaultdict(int)  # + wins / - losses
    reg_weeks = max([r['wk'] for r in rows if r['t'] == 'REG'] or [17])
    out = []
    for r in rows:
        played = r['hs'] is not None and r['as_'] is not None
        g = dict(id=r['id'], t=r['t'], wk=r['wk'], d=r['d'], tm=r['tm'], a=r['a'], h=r['h'])
        if r['n']: g['n'] = 1
        if r['espn']: g['e'] = r['espn']
        if not played:
            if season < 2026: out.append(g)
            continue
        g['as'], g['hs'] = r['as_'], r['hs']
        if r['ot']: g['ot'] = 1
        a, h = r['a'], r['h']
        tie = r['hs'] == r['as_']
        W, L = (None, None) if tie else ((h, a) if r['hs'] > r['as_'] else (a, h))
        ctx = {}
        if r['t'] == 'REG':
            if W:
                ctx = dict(Wpre=tuple(rec[W]), Lpre=tuple(rec[L]), Wstreak=streak[W], Lstreak=max(0, streak[L]))
                rec[W][0] += 1; rec[L][1] += 1
                streak[W] = streak[W] + 1 if streak[W] > 0 else 1
                streak[L] = streak[L] - 1 if streak[L] < 0 else -1
                ctx.update(Wpost=tuple(rec[W]), Lpost=tuple(rec[L]))
            else:
                rec[a][2] += 1; rec[h][2] += 1; streak[a] = 0; streak[h] = 0
        else:
            ctx = dict(Wpre=tuple(rec[W]) if W else (0, 0, 0), Lpre=tuple(rec[L]) if L else (0, 0, 0), Wstreak=0, Lstreak=0,
                       Wpost=tuple(rec[W]) if W else (0, 0, 0), Lpost=tuple(rec[L]) if L else (0, 0, 0))
        g['ar'] = rec_str(*rec[a]); g['hr'] = rec_str(*rec[h])
        facts = dict(conf=conf.get(h, ''), div=r['div'], final_week=(r['t'] == 'REG' and r['wk'] == reg_weeks))
        if W and r['spread'] is not None:
            dog = -r['spread'] if W == h else r['spread']   # spread_line = expected home margin
            facts['dog'] = dog if dog > 0 else 0
        if W and r['elo'] is not None:
            p_w = r['elo'] if W == h else 1 - r['elo']
            facts['elo_upset'] = p_w < 0.3
        mvp, plays = None, []
        if pbp is not None and r['id'] in pbp:
            f2, mvp, plays = analyze(dict(g, **{'as': r['as_']}), pbp[r['id']], season, nick)
            facts.update(f2)
        if r['t'] == 'SB' and season in SB_MVP:
            facts['sbmvp'] = SB_MVP[season]
            if not mvp:
                mvp = dict(n=SB_MVP[season], tm=SB_MVP_TEAM.get(season, W), pos='', l='', off=1)
        gg = dict(g); gg['as'] = r['as_']
        x = dict(b=blurb(gg, ctx or dict(Wpre=(0, 0, 0), Lpre=(0, 0, 0), Wstreak=0, Lstreak=0, Wpost=(0, 0, 0), Lpost=(0, 0, 0)), nick, season, facts))
        if mvp: x['m'] = mvp
        if plays: x['p'] = plays
        rn = {'WC': 'Wild Card', 'DIV': 'Divisional', 'CON': f"{conf.get(h, '')} Championship"}.get(r['t'])
        if r['t'] == 'SB':
            x['y'] = f'{sb_name(season)} highlights'
        elif rn:
            x['y'] = f"{nick[a]} vs {nick[h]} {season} {rn} highlights"
        else:
            x['y'] = f"{nick[a]} vs {nick[h]} {season} week {r['wk']} highlights"
        g['x'] = x
        out.append(g)
    champ = next((g for g in out if g['t'] == 'SB' and 'hs' in g), None)
    data = dict(s=season, rw=reg_weeks, teams=teams, g=out)
    if champ:
        data['champ'] = champ['h'] if champ['hs'] > champ['as'] else champ['a']
    with open(os.path.join(OUT, f'{season}.json'), 'w') as f:
        json.dump(data, f, separators=(',', ':'), ensure_ascii=False)
    return data


if __name__ == '__main__':
    idx = []
    for s in SEASONS:
        d = build(s)
        idx.append(dict(s=s, champ=d.get('champ')))
        n = sum(1 for g in d['g'] if 'x' in g)
        print(s, 'games', len(d['g']), 'with story', n, 'mvp', sum(1 for g in d['g'] if 'm' in g.get('x', {})), flush=True)
