"""The rating model, per team size.

  strength    every unit (a player or a checkpoint net) has a strength theta; a team that is not one player five times has a small
              bonus b over the average of its players. An entry's strength is   sum(weight_u * theta_u) + b   where the weights
              say who takes the pitch at this size (roster.Entry.compose). The chance that A beats B is a logistic of the
              difference (a draw counts half). MAP fit with Gaussian priors (PRIOR_SD for a strength, BONUS_SD for a bonus), Newton's
              method; the covariance of the fit gives every rating's interval.
  scale       pinned: the average rule-based player of the size is BASE (1500). Intervals are relative to that average, so
              adding entries does not move the scale and the uncertainty of "where the whole scale sits" is not in them.
  goals       a Poisson model of the goals of every entry (attack and defence strengths): the goals scored and conceded per match
              against the average opponent, adjusted for who was met (a strong team that only meets strong teams scores less).

All fits take the results summed per pairing (elo/db.py pairings), so a refit costs the same with a thousand games as with a
million. Players and teams come out of the same fit: the rating of a team made of one player is that player's."""
import math

import numpy as np

from . import BASE, BONUS_SD, GOAL_PRIOR_SD, K, PLACEMENT, PRIOR_SD


def valid_groups(ros, size, pairs):
    """The pairings that still count: both entries exist, play this size and are in the file version the games were played with."""
    out = []
    can = {}
    for g in pairs:
        ea, eb = ros.entries.get(g["a"]), ros.entries.get(g["b"])
        if ea is None or eb is None or ea.sha != g["a_sha"] or eb.sha != g["b_sha"]:
            continue
        for e in (ea, eb):
            if e.id not in can:
                can[e.id] = bool(e.compose(size))
        if can[ea.id] and can[eb.id]:
            out.append(g)
    return out


def _record(ids, groups):
    rec = {i: {"games": 0, "w": 0, "d": 0, "l": 0, "gf": 0, "ga": 0} for i in ids}
    for g in groups:
        n, w, d = g["n"], int(g["w"] or 0), int(g["d"] or 0)
        for me, w_, l_, gf, ga in ((g["a"], w, n - w - d, g["ga"], g["gb"]), (g["b"], n - w - d, w, g["gb"], g["ga"])):
            r = rec[me]
            r["games"] += n
            r["w"] += w_
            r["d"] += d
            r["l"] += l_
            r["gf"] += gf
            r["ga"] += ga
    return rec


def fit(ros, size, groups):
    """{entry id: {elo, se, lo, hi, games, w, d, l, gf, ga, placed, bonus}} for every entry that can play `size`. `bonus` is a
    team's bonus in Elo (None for a unit)."""
    ents = ros.at(size)
    units = [i for i, e in ents.items() if e.unit]
    bon = [i for i, e in ents.items() if e.bonus]
    ix = {k: j for j, k in enumerate(units + bon)}
    P = len(ix)
    tau, tau_b = PRIOR_SD / K, BONUS_SD / K
    prec = np.r_[np.full(len(units), 1.0 / tau ** 2), np.full(len(bon), 1.0 / tau_b ** 2)]
    F = {}
    for i, e in ents.items():
        v = np.zeros(P)
        for u, w in e.compose(size).items():
            v[ix[u]] += w
        if e.bonus:
            v[ix[i]] = 1.0
        F[i] = v
    th = np.zeros(P)
    H = -np.diag(prec)
    if groups:
        X = np.array([F[g["a"]] - F[g["b"]] for g in groups])
        n = np.array([g["n"] for g in groups], dtype=float)
        S = np.array([g["score"] for g in groups], dtype=float)
        for _ in range(60):
            p = 1.0 / (1.0 + np.exp(-(X @ th)))
            g_ = X.T @ (S - n * p) - prec * th
            H = -(X.T * (n * p * (1 - p))) @ X - np.diag(prec)
            step = np.linalg.solve(H, g_)
            th -= step
            if np.max(np.abs(step)) < 1e-9:
                break
    C = np.linalg.inv(-H)
    ref_ids = [i for i in units if ents[i].sub == "rules"] or units
    r = np.zeros(P)
    for i in ref_ids:
        r[ix[i]] = 1.0 / len(ref_ids)
    rec = _record(list(ents), groups)
    out = {}
    for i, e in ents.items():
        l = F[i] - r                                   # the rating relative to the average rule-based player
        elo = BASE + K * float(l @ th)
        se = K * math.sqrt(max(float(l @ C @ l), 0.0))
        out[i] = {"elo": elo, "se": se, "lo": elo - 1.96 * se, "hi": elo + 1.96 * se, **rec[i],
                  "placed": rec[i]["games"] >= PLACEMENT, "bonus": K * float(th[ix[i]]) if e.bonus else None}
    return out


def goal_model(ros, size, groups):
    """Attack and defence strength of every entry (a Poisson model: goals of i against j ~ Poisson(exp(mu + att_i - def_j))), MAP
    with N(0, GOAL_PRIOR_SD) priors. Returns {"mu", "att": {id: (value, se)}, "def": ..., "ref": ids that have played, "cov", "ix", "n"}."""
    ids = list(ros.at(size))
    ix = {k: i for i, k in enumerate(ids)}
    n = len(ids)
    sc = np.array([ix[g["a"]] for g in groups] + [ix[g["b"]] for g in groups], dtype=int)
    co = np.array([ix[g["b"]] for g in groups] + [ix[g["a"]] for g in groups], dtype=int)
    y = np.array([g["ga"] for g in groups] + [g["gb"] for g in groups], dtype=float)
    ex = np.array([g["n"] for g in groups] * 2, dtype=float)             # games each observation sums
    th = np.zeros(2 * n + 1)
    th[0] = math.log(max(y.sum() / ex.sum(), 1e-3)) if len(y) else 0.0
    prec = np.r_[0.0, np.full(2 * n, 1.0 / GOAL_PRIOR_SD ** 2)]
    H = -np.diag(prec)
    for _ in range(60 if len(y) else 0):
        lam = ex * np.exp(th[0] + th[1 + sc] - th[1 + n + co])
        r = y - lam
        g_ = -prec * th
        g_[0] += r.sum()
        np.add.at(g_, 1 + sc, r)
        np.add.at(g_, 1 + n + co, -r)
        H = -np.diag(prec)
        H[0, 0] -= lam.sum()
        np.add.at(H[0], 1 + sc, -lam)
        np.add.at(H[0], 1 + n + co, lam)
        H[1:, 0] = H[0, 1:]
        np.add.at(H, (1 + sc, 1 + sc), -lam)
        np.add.at(H, (1 + n + co, 1 + n + co), -lam)
        np.add.at(H, (1 + sc, 1 + n + co), lam)
        np.add.at(H, (1 + n + co, 1 + sc), lam)
        step = np.linalg.solve(H - 1e-9 * np.eye(2 * n + 1), g_)
        th -= step
        if np.max(np.abs(step)) < 1e-9:
            break
    cov = np.linalg.inv(-H + 1e-9 * np.eye(2 * n + 1))
    se = np.sqrt(np.maximum(np.diag(cov), 0.0))
    played = sorted({ids[i] for i in set(sc.tolist())})
    return {"mu": float(th[0]), "att": {k: (float(th[1 + i]), float(se[1 + i])) for k, i in ix.items()},
            "def": {k: (float(th[1 + n + i]), float(se[1 + n + i])) for k, i in ix.items()}, "ref": played, "cov": cov, "ix": ix, "n": n}


def adjusted_goals(gm, att, deff, skip=None):
    """Goals scored and conceded per match against the average opponent of the ladder (the mean over the entries that have played):
    {gf, ga, gf_se, ga_se}. att / deff = (value, se) of the team in question."""
    opp = [k for k in gm["ref"] if k != skip] or gm["ref"]
    if not opp:
        return {"gf": None, "ga": None, "gf_se": None, "ga_se": None}
    gf = sum(math.exp(gm["mu"] + att[0] - gm["def"][j][0]) for j in opp) / len(opp)
    ga = sum(math.exp(gm["mu"] + gm["att"][j][0] - deff[0]) for j in opp) / len(opp)
    return {"gf": gf, "ga": ga, "gf_se": gf * att[1], "ga_se": ga * deff[1]}      # delta method, the team's own uncertainty only


def _goal_se(gm, k, opp):
    """se of an entry's adjusted goals from the full covariance of the fit (mu, attacks and defences are estimated together)."""
    n, ix, cov = gm["n"], gm["ix"], gm["cov"]
    i = ix[k]
    gf_g, ga_g = np.zeros(2 * n + 1), np.zeros(2 * n + 1)
    for j in opp:
        e = math.exp(gm["mu"] + gm["att"][k][0] - gm["def"][j][0]) / len(opp)
        gf_g[0] += e
        gf_g[1 + i] += e
        gf_g[1 + n + ix[j]] -= e
        e = math.exp(gm["mu"] + gm["att"][j][0] - gm["def"][k][0]) / len(opp)
        ga_g[0] += e
        ga_g[1 + ix[j]] += e
        ga_g[1 + n + i] -= e
    return float(np.sqrt(max(gf_g @ cov @ gf_g, 0.0))), float(np.sqrt(max(ga_g @ cov @ ga_g, 0.0)))


def goal_table(gm):
    """{id: {gf, ga, gf_se, ga_se, att, def}}: every entry's opponent-adjusted goals, se from the fit's covariance."""
    out = {}
    for k in gm["att"]:
        opp = [j for j in gm["ref"] if j != k] or gm["ref"]
        g = adjusted_goals(gm, gm["att"][k], gm["def"][k], skip=k)
        if g["gf"] is not None:
            g["gf_se"], g["ga_se"] = _goal_se(gm, k, opp)
        out[k] = {**g, "att": gm["att"][k][0], "def": gm["def"][k][0]}
    return out


def rating_vs_fixed(opp_elo, scores):
    """MAP rating (Elo scale) of one team against opponents whose ratings are held fixed, with the same prior. (elo, se)."""
    tau = PRIOR_SD / K
    th = 0.0
    h = -1.0 / tau ** 2
    for _ in range(60):
        g, h = -th / tau ** 2, -1.0 / tau ** 2
        for oe, s in zip(opp_elo, scores):
            p = 1.0 / (1.0 + math.exp(-(th - (oe - BASE) / K)))
            g += s - p
            h -= p * (1 - p)
        step = g / h
        th -= step
        if abs(step) < 1e-10:
            break
    return BASE + K * th, K / math.sqrt(-h)


def strength_vs_fixed(base, y, sign):
    """MAP attack (sign +1: goals scored, base_k = mu - def_opp) or defence (sign -1: goals conceded, base_k = mu + att_opp) of one
    team against opponents held fixed: y_k ~ Poisson(exp(base_k + sign * x)), prior N(0, GOAL_PRIOR_SD). (x, se)."""
    x = 0.0
    h = -1.0 / GOAL_PRIOR_SD ** 2
    for _ in range(60):
        lam = [math.exp(b + sign * x) for b in base]
        g = sign * sum(yy - l for yy, l in zip(y, lam)) - x / GOAL_PRIOR_SD ** 2
        h = -sum(lam) - 1.0 / GOAL_PRIOR_SD ** 2
        step = g / h
        x -= step
        if abs(step) < 1e-10:
            break
    return x, 1.0 / math.sqrt(-h)
