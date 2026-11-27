"""Which matches to play next, per size. A round is a list of pairs; every pair plays two matches (sides swapped, same seed).

  placement   an entry with fewer than PLACEMENT games is paired first, with opponents spread over the ranking (a random
              quantile each time), so it lands near its place quickly
  informative then the pairs that tell the most: close ratings (p * (1 - p)), uncertain ratings, and pairs that rarely met

An entry plays in at most two pairs of a round."""
from . import PLACEMENT


def pair_games(groups):
    out = {}
    for g in groups:
        key = tuple(sorted((g["a"], g["b"])))
        out[key] = out.get(key, 0) + g["n"]
    return out


def choose_pairs(ids, rat, games, k, rng):
    """Up to k pairs (a, b) from the entries `ids` (rat: {id: {elo, se, games}}, games: pair_games)."""
    order = sorted(ids, key=lambda i: rat[i]["elo"])
    load, pairs = {}, []

    def add(i, j):
        pairs.append((i, j))
        load[i] = load.get(i, 0) + 1
        load[j] = load.get(j, 0) + 1

    new = sorted([i for i in ids if rat[i]["games"] < PLACEMENT], key=lambda i: (rat[i]["games"], rng.random()))
    placed = [i for i in order if rat[i]["games"] >= PLACEMENT] or order
    for i in new:
        if len(pairs) >= k:
            break
        if load.get(i, 0) >= 2:
            continue
        cands = [j for j in placed if j != i and load.get(j, 0) < 2 and games.get(tuple(sorted((i, j))), 0) == 0] or \
                [j for j in placed if j != i and load.get(j, 0) < 2]
        if cands:                                        # spread over the ranking: a random quantile each time
            add(i, cands[min(len(cands) - 1, int(rng.random() * len(cands)))])
    scored = []
    for x in range(len(ids)):
        for y in range(x + 1, len(ids)):
            i, j = ids[x], ids[y]
            p = 1.0 / (1.0 + 10 ** ((rat[j]["elo"] - rat[i]["elo"]) / 400.0))
            info = p * (1 - p) * (rat[i]["se"] ** 2 + rat[j]["se"] ** 2) / (1 + games.get(tuple(sorted((i, j))), 0))
            scored.append((info * (0.9 + 0.2 * rng.random()), i, j))
    for _, i, j in sorted(scored, reverse=True):
        if len(pairs) >= k:
            break
        if load.get(i, 0) < 2 and load.get(j, 0) < 2 and (i, j) not in pairs and (j, i) not in pairs:
            add(i, j)
    return pairs


def pick_size(sizes, summary):
    """The size to play next: one that still has unplaced entries (the most of them first), else the one with the fewest
    games per entry. summary: {size: (entries, unplaced, games)}."""
    todo = [s for s in sizes if summary[s][0] >= 2]
    if not todo:
        return None
    unplaced = [s for s in todo if summary[s][1] > 0]
    if unplaced:
        return max(unplaced, key=lambda s: summary[s][1])
    return min(todo, key=lambda s: summary[s][2] / summary[s][0])
