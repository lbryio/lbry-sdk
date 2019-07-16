import 'dart:async';
import 'dart:convert';

import 'package:web_socket_channel/io.dart';
import 'package:web_socket_channel/status.dart' as status;


class ServerConnection {
    String url = "";
    IOWebSocketChannel channel;
    bool get isConnected => channel != null && channel.closeCode == null;

    final StreamController<ServerLoadDataPoint> _loadDataController = StreamController.broadcast();
    Stream<ServerLoadDataPoint> get load_data => _loadDataController.stream;

    ServerConnection({this.url});

    open() {
        if (isConnected) return Future.value('already open');
        channel = IOWebSocketChannel.connect(this.url);
        int tick = 1;
        channel.stream.listen((message) {
            Map data = json.decode(message);
            print(data);
            Map commands = data['commands'] ?? {};
            _loadDataController.add(
                ServerLoadDataPoint(
                    tick,
                    APICallMetrics.from_map(commands['search'] ?? {}),
                    APICallMetrics.from_map(commands['resolve'] ?? {})
                )
            );
            tick++;
        });
    }

    close() {
        if (isConnected) {
            return channel.sink.close(status.goingAway);
        }
        return Future.value('already closed');
    }

    subscribe_to_server_load_data() {
        if (isConnected) channel.sink.add('subscribe');
    }

    unsubscribe_from_server_load_data() {
        if (isConnected) channel.sink.add('unsubscribe');
    }

}


class APICallMetrics {
    final int started;
    final int finished;
    final int total_time;
    final int execution_time;
    final int query_time;
    final int query_count;
    final int cache_hit;
    final int avg_wait_time;
    final int avg_total_time;
    final int avg_execution_time;
    final int avg_query_time_per_search;
    final int avg_query_time_per_query;
    APICallMetrics(
        this.started, this.finished, this.total_time, this.execution_time,
        this.query_time, this.query_count, this.cache_hit):
        avg_wait_time=finished > 0 ? ((total_time - (execution_time + query_time))/finished).round() : 0,
        avg_total_time=finished > 0 ? (total_time/finished).round() : 0,
        avg_execution_time=finished > 0 ? (execution_time/finished).round() : 0,
        avg_query_time_per_search=finished > 0 ? (query_time/finished).round() : 0,
        avg_query_time_per_query=query_count > 0 ? (query_time/query_count).round() : 0;
    APICallMetrics.from_map(Map data): this(
        data['started'] ?? 0,
        data['finished'] ?? 0,
        data['total_time'] ?? 0,
        data['execution_time'] ?? 0,
        data['query_time'] ?? 0,
        data['query_count'] ?? 0,
        data['cache_hit'] ?? 0,
    );
}


class ServerLoadDataPoint {
    final int tick;
    final APICallMetrics search;
    final APICallMetrics resolve;
    ServerLoadDataPoint(this.tick, this.search, this.resolve);
    ServerLoadDataPoint.empty():
        tick = 0,
        search=APICallMetrics.from_map({}),
        resolve=APICallMetrics.from_map({});
}


connect_and_listen_for_load_data() {
    ServerConnection(url: 'ws://localhost:8181/')..open()..load_data.listen((m) {
        print(m.search);
    });
}
