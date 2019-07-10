import 'dart:async';
import 'dart:io';
import 'dart:convert';


class LoadRequest {

    static const RESOLVE = {
        'id': 1,
        'method': 'blockchain.claimtrie.resolve',
        'params': ['one', 'two', 'three']
    };

    static const CLAIM_SEARCH = {
        'id': 1,
        'method': 'blockchain.claimtrie.search',
        'params': {
            'fee_amount': '<1',
            'all_tags': ['funny'],
            'any_tags': [
                'crypto',
                'outdoors',
                'cars',
                'automotive'
            ]
        }
    };

    final Map payload;
    Completer completer;
    Stopwatch timer;

    bool get isDone => completer.isCompleted;
    int get elapsed => timer.elapsedMilliseconds;

    LoadRequest.search(): payload=CLAIM_SEARCH;
    LoadRequest.resolve(): payload=RESOLVE;

    LoadRequest start() {
        completer = Completer();
        timer = Stopwatch()..start();
        completer.future.whenComplete(() => timer.stop());
        try {
            Socket.connect('127.0.0.1', 50001).then((socket) {
                socket.transform(utf8.decoder).listen((r) {
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

typedef bool LoadTestCallback(LoadGenerator load_generator, LoadDataPoint stats);

class LoadGenerator {
    int load = 1;
    Timer _timer;

    LoadTestCallback cb;

    LoadGenerator(this.cb);

    start() {
        var previous = spawn_requests();
        var backlog = <LoadRequest>[];
        _timer = Timer.periodic(Duration(seconds: 1), (t) {
            var stat = LoadDataPoint();
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
            if (cb(this, stat)) {
                previous = spawn_requests();
            } else {
                t.cancel();
            }
        });
    }

    stop() {
        _timer.cancel();
    }

    List<LoadRequest> spawn_requests() {
        var requests = <LoadRequest>[];
        for (var _ in Iterable.generate(load)) {
            requests.add(LoadRequest.search().start());
        }
        return requests;
    }

}

class LoadDataPoint {
    final DateTime time = new DateTime.now();
    int success = 0;
    int errored = 0;
    int backlog = 0;
    int catchup = 0;
    int _success_total = 0;
    int _catchup_total = 0;
    int load = 0;

    int get avg_success => _success_total > 0 ? (_success_total/success).round() : 0;
    int get avg_catchup => _catchup_total > 0 ? (_catchup_total/catchup).round() : 0;

    addSuccess(LoadRequest r) {
        success++; _success_total += r.elapsed;
    }

    addCatchup(LoadRequest r) {
        catchup++; _catchup_total += r.elapsed;
    }
}

cli() {
    var runs = 1;
    LoadGenerator((t, stats) {
        print("run ${runs}: ${stats}");
        t.load = (runs < 4 ? t.load*2 : t.load/2).round();
        return runs++ < 10;
    }).start();
}
