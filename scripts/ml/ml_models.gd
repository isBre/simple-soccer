class_name MLModels
extends RefCounted
## Cached loader for the trained nets that drive a whole team (TeamDef.ml_model).
## Thread-safe: SimBatch builds matches on worker threads and the MLP is read-only after loading.

static var _cache: Dictionary = {}
static var _mutex := Mutex.new()


## Returns the net, or null when the file is missing or the net does not fit this team size
## (observation = 8 * size + 9 values, +5 with the slot one-hot; 8 * size + 6 for the role-free team observation).
static func load_for(path: String, team_size: int) -> MLP:
    _mutex.lock()
    var net: MLP = _cache.get(path)
    if net == null and not _cache.has(path):
        var d = Database.read_json(path)
        if d is Dictionary and d.has("W"):
            net = MLP.from_dict(d)
        _cache[path] = net
    _mutex.unlock()
    if net == null:
        return null
    var n_in: int = net.sizes[0]
    if n_in != 8 * team_size + 9 and n_in != 8 * team_size + 14 and n_in != 8 * team_size + 6:       # ego (+ slot) layouts and the team layout
        return null
    return net
