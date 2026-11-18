class_name SimBatch
extends RefCounted
## Plays many matches in parallel (tournament rounds): each one on a worker thread, played to the end by the match core
## (MatchClient.run: one forked server process per match, so they use all cores).

var configs: Array = []
var results: Array = []
var _tasks: Array[int] = []
var _mutex := Mutex.new()
var _done := 0


func start(cfgs: Array) -> void:
    configs = cfgs
    results.resize(cfgs.size())
    for i in cfgs.size():
        _tasks.append(WorkerThreadPool.add_task(_run.bind(i), true, "match sim"))


func _run(i: int) -> void:
    var r := MatchClient.run(configs[i])
    _mutex.lock()
    results[i] = r
    _done += 1
    _mutex.unlock()


func progress() -> float:
    if configs.is_empty():
        return 1.0
    return float(_done) / float(configs.size())


func is_done() -> bool:
    return _done >= configs.size()


func finish() -> void:
    for t in _tasks:
        WorkerThreadPool.wait_for_task_completion(t)
