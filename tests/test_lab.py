"""The Lab's experiment specs (lab/tracker.py), without training anything:
  curriculum   a curriculum spec becomes one spec per stage, in order: <name>_1v0, <name>_1v1, ..., the first from scratch, each
               next from the previous stage's best checkpoint, all on the slots observation, sizes and opponents as given
  validation   the stages of a curriculum are valid together (a stage may start from an earlier stage of the same batch); a
               size below 5 without the slots observation, an unknown opponent mode or a missing start are refused
  setup        the run page's Setup tab (lab/dashboard.py training_setup) tells the truth: each observation layout's blocks
               (rl/selfplay_args.py OBS_LAYOUT) add up to the numbers the real features give, block by block; every reward option
               has its group, who gets it and when; every tuning setting is a real option

  python3 tests/test_lab.py"""
import sys

from lab import tracker


def check(name, ok, detail=""):
    print("%-11s %s    %s" % (name, "OK" if ok else "FAIL", detail))
    return ok


def main():
    spec = {"name": "zz_test_cur", "updates": 300, "args": {"seed": 3, "elo_pairs": 8}, "plateau": 3, "notes": "test",
            "stages": [{"size": 1, "opp": "none", "updates": 150}, {"size": 1}, {"size": 2, "updates": 400, "args": {"lr": 5e-5}},
                       {"size": 5, "min_updates": 200}]}
    st = tracker.expand(spec)
    names = [s["name"] for s in st]
    ok = check("curriculum", names == ["zz_test_cur_1v0", "zz_test_cur_1v1", "zz_test_cur_2v2", "zz_test_cur_5v5"]
               and st[0]["start"] == "scratch" and st[1]["start"] == "best:zz_test_cur_1v0" and st[3]["start"] == "best:zz_test_cur_2v2"
               and all(s["obs"] == "slots" and s["curriculum"] == "zz_test_cur" for s in st)
               and [s["size"] for s in st] == [1, 1, 2, 5] and st[0]["opp"] == "none" and st[1]["opp"] == "rules"
               and st[2]["args"] == {"seed": 3, "elo_pairs": 8, "lr": 5e-5} and st[0]["updates"] == 150 and st[1]["updates"] == 300
               and tracker.start_model(st[0]) is None and tracker.start_model(st[2]) == "out_5v5/ckpt/x_zz_test_cur_1v1_best.pt"
               and tracker.expand({"name": "plain", "start": "x.pt"}) == [{"name": "plain", "start": "x.pt"}],
               " -> ".join(names))
    errs, earlier = [], []
    for s in st:
        errs += tracker.validate_spec(s, earlier)
        earlier.append(s["name"])
    bad = [tracker.validate_spec({"name": "zz_bad_a", "start": "scratch", "size": 3}),
           tracker.validate_spec({"name": "zz_bad_b", "start": "scratch", "obs": "slots", "size": 2, "opp": "keeper"}),
           tracker.validate_spec({"name": "zz_bad_c", "start": "best:zz_never_ran", "obs": "slots", "size": 2})]
    ok &= check("validation", not errs and all(bad), "stages valid together%s; refused: %s" % (
        " (" + "; ".join(errs) + ")" if errs else "", " | ".join(b[0] for b in bad if b)))
    ok &= setup_check()
    print("TOTAL -> %s" % ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


def setup_check():
    from lab import dashboard
    from rl import selfplay_args as sa
    from soccer.ai import nets, obs
    from soccer.match import Match, make_config
    m = Match(make_config("rl_team_5", "ember", "arena", 5, 90.0, 1))
    m.kickoff_active, p = True, m.team_lists[0][0]       # a kickoff: the flags are 1, so a misplaced flag shows below
    feats = {"slots": obs.features_slots(m, p), "team": obs.features_team(m, p), "rank": obs.features_rank(m, p), "legacy": obs.features_ego(m, p)}
    bad = []
    for name, layout in sa.OBS_LAYOUT.items():
        blocks = dashboard.obs_blocks(sa, name, 5, "rules")
        if blocks[-1]["to"] + 1 != sa.OBS_DIMS[name] or len(feats[name]) != sa.OBS_DIMS[name]:
            bad.append("%s: %d blocks, %d features, %d declared" % (name, blocks[-1]["to"] + 1, len(feats[name]), sa.OBS_DIMS[name]))
        flags = next((b for b in blocks if b["block"] == "flags"), None)
        if flags and feats[name][flags["from"]] != 1.0:                    # "kickoff on" is the first flag of every layout that has flags
            bad.append("%s: kickoff flag not at %d" % (name, flags["from"]))
    small = {b["block"]: b.get("filled") for b in dashboard.obs_blocks(sa, "slots", 3, "rules")}
    empty = {b["block"]: b.get("filled") for b in dashboard.obs_blocks(sa, "slots", 1, "none")}
    if (small["teammates"], small["opponents"], empty["teammates"], empty["opponents"]) != (2, 3, 0, 0):
        bad.append("filled slots %s / %s" % (small, empty))
    opts = {a.dest for a in sa.parser()._actions}
    missing = [k for k in opts if (k.startswith("w_") or k == "shaping") and k not in dashboard.REWARD_INFO]
    params = [k for d in list(dashboard.TERM_PARAMS.values()) + list(dashboard.GROUP_PARAMS.values()) for k in d if k not in opts]
    groups = [g for g, *_ in dashboard.REWARD_INFO.values() if g not in dashboard.REWARD_GROUPS]
    keys = [k for _, ks in dashboard.TRAINING_GROUPS for k in ks if k not in opts]
    heads = [h["outputs"] for h in dashboard.action_heads(nets.CALL_OUT)], [h["outputs"] for h in dashboard.action_heads(10)]
    if heads != (["0–8", "9", "10–14"], ["0–8", "9", "–"]):
        bad.append("heads %s" % (heads,))
    bad += ["no REWARD_INFO for " + ", ".join(missing)] if missing else []
    bad += ["unknown options " + ", ".join(params + keys)] if params or keys else []
    bad += ["unknown groups " + ", ".join(groups)] if groups else []
    return check("setup", not bad, "; ".join(bad) or "%d layouts match their features, %d reward terms described" % (len(sa.OBS_LAYOUT), len(dashboard.REWARD_INFO)))


if __name__ == "__main__":
    sys.exit(main())
