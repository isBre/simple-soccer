"""Players (data/players/*.json): a player is a brain with a name. Every player on the pitch has the same body (speed, kick,
size); what differs is how it decides. Three kinds:

  rules   the rule-based AI (soccer/ai/rules.py) with a playing style (data/styles) and a skill 0-100
  opus    the Opus planner (soccer/ai/opus.py) with its style and a skill
  net     a trained neural net (`model`, a game-model JSON); it can only play the team sizes its observation fits

`skill` only changes the AI's precision and reaction (soccer/ai/skill.py: aim errors, positioning noise, perception delay,
thinking time), never the physics. A net ignores it; it is kept so rule-based opponents read every player the same way.
There are no positions and no keeper: which formation spot a player takes is the team's tactic (soccer/teams.py)."""
import json
import os

KINDS = ("rules", "opus", "net")
SIZES = (1, 2, 3, 4, 5)
DEFAULT_SKILL = 70


class PlayerDef:
    def __init__(self, d, root):
        self.raw = d
        self.id = str(d.get("id", ""))
        self.name = str(d.get("name", self.id))
        self.kind = str(d.get("kind", "rules"))
        if self.kind not in KINDS:
            raise ValueError("player %s: unknown kind %r (one of %s)" % (self.id, self.kind, ", ".join(KINDS)))
        self.style_id = str(d.get("style", "opus_high" if self.kind == "opus" else "balanced"))
        self.skill = int(d.get("skill", DEFAULT_SKILL))
        self.model = str(d.get("model", ""))            # net: path from the project root
        self.description = str(d.get("description", ""))
        self.origin = d.get("origin", {})                # how it was made (nets: run, recipe, start net, date, rating)
        self.hidden = bool(d.get("hidden", False))       # kept for old matches, not offered in the game
        self._root = root
        self._n_in = None
        if self.kind == "net" and not self.model:
            raise ValueError("player %s: a net player needs a model" % self.id)

    @property
    def model_path(self):
        return os.path.join(self._root, self.model) if self.model else ""

    @property
    def n_in(self):
        """Input size of a net player's model (None for rule-based players)."""
        if self.kind != "net":
            return None
        if self._n_in is None:
            with open(self.model_path) as f:
                self._n_in = int(json.load(f)["sizes"][0])
        return self._n_in

    def sizes(self):
        """Team sizes this player can play (a net only those its observation fits)."""
        if self.kind != "net":
            return list(SIZES)
        from .ai.nets import fits
        return [n for n in SIZES if fits(self.n_in, n)]

    def can_play(self, size):
        return size in self.sizes()

    def to_dict(self):
        return {"id": self.id, "name": self.name, "kind": self.kind, "style": self.style_id, "skill": self.skill,
                "model": self.model, "description": self.description, "origin": self.origin, "sizes": self.sizes(),
                "hidden": self.hidden}
