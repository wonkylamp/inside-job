"""How unusual are the 3 headroom games among 3-game draws from the 40 pilot games? Plus each game's story."""
import json, random, collections, itertools
idx = [json.loads(l) for l in open("games/index.jsonl")]
def per_game(r):
    ev = [json.loads(l) for l in open(r["log"]) if l.strip()]
    role = {e["player"]: e["role"] for e in ev if e["type"] == "role"}
    model = {p["name"]: p["model_name"] for p in r["players"]}
    moles = {p for p, x in role.items() if x == "mole"}
    g = dict(cv=0, cvm=0, sm=0, smn=0, sc=0, scn=0, el=0, elm=0, story=[])
    for e in ev:
        if e["type"] == "vote_result":
            for v, t in e["votes"].items():
                if v not in moles: g["cv"] += 1; g["cvm"] += t in moles
            if e.get("eliminated"): g["el"] += 1; g["elm"] += e["role"] == "mole"
            g["story"].append(f"R{e['round']} vote: {e['tally']} -> out {e.get('eliminated')} ({e.get('role')}, {model.get(e.get('eliminated'))})")
        elif e["type"] == "job_pick":
            g["story"].append(f"R{e['round']} leader {e['leader']}{'*' if e['leader'] in moles else ''} team {[p+('*' if p in moles else '') for p in e['team']]}")
        elif e["type"] == "job_choices":
            g["story"].append(f"   choices {e['choices']}")
        elif e["type"] == "turn" and e["turn_phase"] == "vote" and e["player"] not in moles:
            for p, v in ((e.get("action") or {}).get("suspicion") or {}).items():
                if p in moles: g["sm"] += v; g["smn"] += 1
                elif p in role: g["sc"] += v; g["scn"] += 1
    g["moles"] = sorted(moles); g["win"] = r["winner"]
    return g
P = [per_game(r) for r in idx if r.get("batch") in ("pilot1", "pilot2") and not r.get("spoiled")]
H = [per_game(r) for r in idx if r.get("batch") == "headroom1"]
def pooled(gs):
    cv = sum(g["cv"] for g in gs); cvm = sum(g["cvm"] for g in gs)
    gap = sum(g["sm"] for g in gs) / max(1, sum(g["smn"] for g in gs)) - sum(g["sc"] for g in gs) / max(1, sum(g["scn"] for g in gs))
    elm = sum(g["elm"] for g in gs) / max(1, sum(g["el"] for g in gs))
    wins = sum(g["win"] == "moles" for g in gs)
    return cvm / cv, gap, elm, wins
h = pooled(H)
print("headroom: crew votes on mole %.2f, suspicion gap %+.1f, elims on mole %.2f, mole wins %d" % h)
print("pilots (40): crew votes on mole %.2f, suspicion gap %+.1f, elims on mole %.2f, mole wins %d" % pooled(P))
rng = random.Random(1); N = 20000; c = [0, 0, 0, 0, 0]
for _ in range(N):
    d = pooled(rng.sample(P, 3))
    c[0] += d[0] <= h[0]; c[1] += d[1] <= h[1]; c[2] += d[2] <= h[2]; c[3] += d[3] >= h[3]
    c[4] += d[0] <= h[0] and d[1] <= h[1]
print("share of 3-game pilot draws at least as extreme: votes %.4f  gap %.4f  elims %.4f  wins>=2 %.4f  votes&gap %.4f" % tuple(x / N for x in c))
print("per pilot game, crew-vote-on-mole share sorted:", sorted(round(g["cvm"] / g["cv"], 2) for g in P))
print("per pilot game, suspicion gap sorted:", sorted(round(g["sm"] / max(1, g["smn"]) - g["sc"] / max(1, g["scn"])) for g in P))
for r, g in zip([r for r in idx if r.get("batch") == "headroom1"], H):
    print(f"\nseed {r['seed']} moles {g['moles']} winner {g['win']}: crew votes on mole {g['cvm']}/{g['cv']}, gap {g['sm']/max(1,g['smn'])-g['sc']/max(1,g['scn']):+.1f}")
    for s in g["story"]: print("  ", s)
