class_name RemoteMLP
extends MLP
## MLP whose forward pass runs in tools/net_server.py (numpy) instead of GDScript: for the live viewer on slow machines.

var peer := StreamPeerTCP.new()


## The server announces the net's input size when we connect, so MLBot builds the matching observation (46 = team layout, 54 = ego with slot).
func _init(port: int) -> void:
    super(PackedInt32Array())
    peer.connect_to_host("127.0.0.1", port)
    while peer.get_status() == StreamPeerTCP.STATUS_CONNECTING:
        peer.poll()
        OS.delay_msec(5)
    peer.set_no_delay(true)
    var header := peer.get_data(4)
    var n_in := 54
    if header[0] == OK:
        n_in = (header[1] as PackedByteArray).decode_u32(0)
    sizes = PackedInt32Array([n_in, 128, 128, 10])


func forward(x: PackedFloat32Array) -> PackedFloat32Array:
    peer.put_data(x.to_byte_array())
    var r := peer.get_data(40)
    return (r[1] as PackedByteArray).to_float32_array()
