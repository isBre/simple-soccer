extends Node
## Prints Godot's RandomNumberGenerator output for a few seeds (exact bits, hex), for tests/test_rng.py.

func _ready() -> void:
    var out := {}
    for s in [0, 1, 42, 123456789, 1099511627781, -7, 4294967295]:
        var r := RandomNumberGenerator.new()
        r.seed = s
        var d := {"state0": str(r.state)}
        var ints := []
        var f := PackedFloat64Array()
        for i in 40:
            ints.append(r.randi())
        for i in 40:
            f.append(r.randf())
        for i in 40:
            f.append(r.randfn(0.0, 1.0))
        for i in 40:
            f.append(r.randfn(0.0, 0.55))
        for i in 40:
            f.append(r.randf_range(-10.0, 10.0))
        for i in 40:
            f.append(r.randf_range(0.0, 3.0))
        for i in 40:
            ints.append(r.randi_range(6, 28))
        for i in 40:
            ints.append(r.randi_range(-3, 1000003))
        d["ints"] = ints
        d["floats"] = Marshalls.raw_to_base64(f.to_byte_array())
        d["state1"] = str(r.state)
        out[str(s)] = d
    print("RNG " + JSON.stringify(out))
    get_tree().quit()
