class_name RemoteMLP
extends MLP
## MLP whose forward pass runs in tools/net_server.py (numpy) instead of GDScript: for the live viewer on slow machines.

var peer := StreamPeerTCP.new()


func _init(port: int, n_in: int = 54) -> void:
    super(PackedInt32Array())
    sizes = PackedInt32Array([n_in, 128, 128, 10])
    peer.connect_to_host("127.0.0.1", port)
    while peer.get_status() == StreamPeerTCP.STATUS_CONNECTING:
        peer.poll()
        OS.delay_msec(5)
    peer.set_no_delay(true)


func forward(x: PackedFloat32Array) -> PackedFloat32Array:
    peer.put_data(x.to_byte_array())
    var r := peer.get_data(40)
    return (r[1] as PackedByteArray).to_float32_array()
