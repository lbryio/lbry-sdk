import 'dart:async';
import 'dart:io';
import 'dart:convert';


class LoadRequest {
    final String host;
    final int port;
    final Map payload;
    Completer completer;
    Stopwatch timer;

    bool get isDone => completer.isCompleted;
    int get elapsed => timer.elapsedMilliseconds;

    LoadRequest(this.host, this.port, this.payload);

    LoadRequest start() {
        completer = Completer();
        timer = Stopwatch()..start();
        completer.future.whenComplete(() => timer.stop());
        try {
            Socket.connect(this.host, this.port).then((socket) {
                utf8.decoder.bind(socket).listen((r) {
                    if (r.contains('"jsonrpc": "2.0", "result": ')) {
                        socket.close();
                        completer.complete();
                    }
                }, onError: (e) {print(e); completer.complete();});
                try {
                    socket.write(jsonEncode(payload) + '\n');
                } catch (exception, stackTrace) {
                    print(exception);
                    print(stackTrace);
                    completer.complete();
                }
            }, onError: (e) {print(e);completer.complete();});
        } catch (exception, stackTrace) {
            print(exception);
            print(stackTrace);
            completer.complete();
        }
        return this;
    }
}

typedef bool LoadTickCallback(ClientLoadGenerator load_generator, ClientLoadDataPoint stats);

class ClientLoadGenerator {
    Timer _timer;

    final String host;
    final int port;
    final LoadTickCallback tickCallback;
    int load = 1;
    Map query;

    ClientLoadGenerator(this.host, this.port, {this.tickCallback, this.query}) {
        if (query == null) {
            query = {
                'id': 1,
                'method': 'blockchain.claimtrie.resolve',
                'params': ['one', 'two', 'three']
            };
        }
    }

    start() {
        var previous = spawn_requests();
        var backlog = <LoadRequest>[];
        _timer = Timer.periodic(Duration(seconds: 1), (t) {
            var stat = ClientLoadDataPoint(t.tick);
            backlog.removeWhere((r) {
                if (r.isDone) stat.addCatchup(r);
                return r.isDone;
            });
            for (var f in previous) {
                if (f.isDone) {
                    stat.addSuccess(f);
                } else {
                    backlog.add(f);
                }
            }
            stat.backlog = backlog.length;
            stat.load = load;
            stat.close();
            if (tickCallback(this, stat)) {
                previous = spawn_requests();
            } else {
                stop();
            }
        });
    }

    stop() {
        _timer.cancel();
    }

    List<LoadRequest> spawn_requests() {
        var requests = <LoadRequest>[];
        for (var _ in Iterable.generate(load)) {
            requests.add(LoadRequest(this.host, this.port, this.query).start());
        }
        return requests;
    }

}

class ClientLoadDataPoint {
    final int tick;
    int success = 0;
    int errored = 0;
    int backlog = 0;
    int catchup = 0;
    int _success_total = 0;
    int avg_success = 0;
    int _catchup_total = 0;
    int avg_catchup = 0;
    int load = 0;

    ClientLoadDataPoint(this.tick);
    ClientLoadDataPoint.empty(): this(0);

    addSuccess(LoadRequest r) {
        success++; _success_total += r.elapsed;
    }

    addCatchup(LoadRequest r) {
        catchup++; _catchup_total += r.elapsed;
    }

    close() {
        avg_success = _success_total > 0 ? (_success_total/success).round() : 0;
        avg_catchup = _catchup_total > 0 ? (_catchup_total/catchup).round() : 0;
    }

}


generate_load() {
    var runs = 1;
    ClientLoadGenerator('localhost', 50001, tickCallback: (t, stats) {
        print("run ${runs}: ${stats.load} load, ${stats.success} success, ${stats.backlog} backlog");
        t.load = (runs < 4 ? t.load*2 : t.load/2).round();
        return runs++ < 10;
    }).start();
}
