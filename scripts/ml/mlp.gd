class_name MLP
extends RefCounted
## Tiny dependency-free MLP (ReLU hidden layers, linear output) with Adam.
## Output convention used by MLBot: [0..8] move logits (softmax), [9] kick logit (sigmoid).

var sizes := PackedInt32Array()
var W: Array = []       # W[l]: PackedFloat32Array, index o * n_in + i
var B: Array = []
var _mW: Array = []
var _vW: Array = []
var _mB: Array = []
var _vB: Array = []
var _t := 0
var kick_bias := 0.0     # added to the kick logit at play time (undoes the class weight used in training)


func _init(layer_sizes: PackedInt32Array = PackedInt32Array(), rng: RandomNumberGenerator = null) -> void:
    sizes = layer_sizes
    if sizes.size() < 2:
        return
    if rng == null:
        rng = RandomNumberGenerator.new()
    for l in sizes.size() - 1:
        var n_in: int = sizes[l]
        var n_out: int = sizes[l + 1]
        var w := PackedFloat32Array()
        w.resize(n_in * n_out)
        var std := sqrt(2.0 / n_in)
        for k in w.size():
            w[k] = rng.randfn(0.0, std)
        var b := PackedFloat32Array()
        b.resize(n_out)
        W.append(w)
        B.append(b)
        _mW.append(_zeros(w.size()))
        _vW.append(_zeros(w.size()))
        _mB.append(_zeros(n_out))
        _vB.append(_zeros(n_out))


static func _zeros(n: int) -> PackedFloat32Array:
    var a := PackedFloat32Array()
    a.resize(n)
    return a


func forward(x: PackedFloat32Array) -> PackedFloat32Array:
    var a := x
    var last := W.size() - 1
    for l in W.size():
        a = _layer(l, a, l < last)
    return a


func _layer(l: int, a: PackedFloat32Array, relu: bool) -> PackedFloat32Array:
    var w: PackedFloat32Array = W[l]
    var b: PackedFloat32Array = B[l]
    var n_in := a.size()
    var n_out := b.size()
    var out := PackedFloat32Array()
    out.resize(n_out)
    for o in n_out:
        var s: float = b[o]
        var base := o * n_in
        for i in n_in:
            s += w[base + i] * a[i]
        if relu and s < 0.0:
            s = 0.0
        out[o] = s
    return out


## Supervised training for the (9-way move, kick) head. X is flat, n_in floats per sample.
func fit(X: PackedFloat32Array, ym: PackedInt32Array, yk: PackedInt32Array, epochs: int,
        batch: int, lr: float, kick_weight: float, rng: RandomNumberGenerator) -> void:
    var n_in: int = sizes[0]
    var n := ym.size()
    var idx := PackedInt32Array()
    idx.resize(n)
    for i in n:
        idx[i] = i
    var L := W.size()
    for ep in epochs:
        for i in range(n - 1, 0, -1):   # Fisher-Yates
            var j := rng.randi() % (i + 1)
            var tmp := idx[i]
            idx[i] = idx[j]
            idx[j] = tmp
        var loss := 0.0
        var correct := 0
        var pos := 0
        var start := 0
        while start < n:
            var end := mini(start + batch, n)
            var gW: Array = []
            var gB: Array = []
            for l in L:
                gW.append(_zeros((W[l] as PackedFloat32Array).size()))
                gB.append(_zeros((B[l] as PackedFloat32Array).size()))
            for s in range(start, end):
                var si := idx[s]
                var acts: Array = [X.slice(si * n_in, (si + 1) * n_in)]
                for l in L:
                    acts.append(_layer(l, acts[l], l < L - 1))
                var z: PackedFloat32Array = acts[L]
                # softmax over 9 move logits
                var mx := z[0]
                for k in range(1, 9):
                    mx = maxf(mx, z[k])
                var sum := 0.0
                var pr := PackedFloat32Array()
                pr.resize(9)
                for k in 9:
                    pr[k] = exp(z[k] - mx)
                    sum += pr[k]
                var best := 0
                for k in 9:
                    pr[k] /= sum
                    if pr[k] > pr[best]:
                        best = k
                if best == ym[si]:
                    correct += 1
                loss -= log(maxf(pr[ym[si]], 1e-6))
                var pk := 1.0 / (1.0 + exp(-z[9]))
                var wk := kick_weight if yk[si] == 1 else 1.0
                if yk[si] == 1:
                    pos += 1
                    loss -= log(maxf(pk, 1e-6)) * wk
                else:
                    loss -= log(maxf(1.0 - pk, 1e-6))
                var delta := PackedFloat32Array()
                delta.resize(10)
                for k in 9:
                    delta[k] = pr[k] - (1.0 if k == ym[si] else 0.0)
                delta[9] = (pk - float(yk[si])) * wk
                for l in range(L - 1, -1, -1):
                    var a_prev: PackedFloat32Array = acts[l]
                    var w: PackedFloat32Array = W[l]
                    var gw: PackedFloat32Array = gW[l]
                    var gb: PackedFloat32Array = gB[l]
                    var m_in := a_prev.size()
                    var m_out := delta.size()
                    var nd := _zeros(m_in)
                    for o in m_out:
                        var d := delta[o]
                        if d == 0.0:
                            continue
                        gb[o] += d
                        var base := o * m_in
                        for i in m_in:
                            gw[base + i] += d * a_prev[i]
                            nd[i] += w[base + i] * d
                    if l > 0:
                        for i in m_in:
                            if a_prev[i] <= 0.0:
                                nd[i] = 0.0
                    gW[l] = gw
                    gB[l] = gb
                    delta = nd
            _adam(gW, gB, lr, float(end - start))
            start = end
        print("[mlp] epoch %d/%d loss %.3f move-acc %.1f%% kick+ %.1f%%" % [
            ep + 1, epochs, loss / n, 100.0 * correct / n, 100.0 * pos / n])


func _adam(gW: Array, gB: Array, lr: float, count: float) -> void:
    _t += 1
    var b1 := 0.9
    var b2 := 0.999
    var c1 := 1.0 - pow(b1, _t)
    var c2 := 1.0 - pow(b2, _t)
    for l in W.size():
        _adam_step(W[l], gW[l], _mW[l], _vW[l], lr, count, b1, b2, c1, c2)
        _adam_step(B[l], gB[l], _mB[l], _vB[l], lr, count, b1, b2, c1, c2)


func _adam_step(p: PackedFloat32Array, g: PackedFloat32Array, m: PackedFloat32Array, v: PackedFloat32Array,
        lr: float, count: float, b1: float, b2: float, c1: float, c2: float) -> void:
    for k in p.size():
        var gk := g[k] / count
        m[k] = b1 * m[k] + (1.0 - b1) * gk
        v[k] = b2 * v[k] + (1.0 - b2) * gk * gk
        p[k] -= lr * (m[k] / c1) / (sqrt(v[k] / c2) + 1e-8)


func get_params() -> PackedFloat32Array:
    var out := PackedFloat32Array()
    for l in W.size():
        out.append_array(W[l])
        out.append_array(B[l])
    return out


func set_params(p: PackedFloat32Array) -> void:
    var k := 0
    for l in W.size():
        var w: PackedFloat32Array = W[l]
        for i in w.size():
            w[i] = p[k]
            k += 1
        W[l] = w
        var b: PackedFloat32Array = B[l]
        for i in b.size():
            b[i] = p[k]
            k += 1
        B[l] = b


## Copy for inference (no optimizer state).
func clone() -> MLP:
    var m := MLP.new()
    m.sizes = sizes
    m.kick_bias = kick_bias
    for l in W.size():
        m.W.append((W[l] as PackedFloat32Array).duplicate())
        m.B.append((B[l] as PackedFloat32Array).duplicate())
    return m


func to_dict() -> Dictionary:
    var ws: Array = []
    var bs: Array = []
    for l in W.size():
        ws.append(Array(W[l]))
        bs.append(Array(B[l]))
    return {"sizes": Array(sizes), "W": ws, "B": bs, "kick_bias": kick_bias}


static func from_dict(d: Dictionary) -> MLP:
    var m := MLP.new()
    m.sizes = PackedInt32Array(d["sizes"])
    m.kick_bias = float(d.get("kick_bias", 0.0))
    for l in (d["W"] as Array).size():
        m.W.append(PackedFloat32Array(d["W"][l]))
        m.B.append(PackedFloat32Array(d["B"][l]))
    return m
