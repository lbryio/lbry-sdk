import 'dart:async';
import 'dart:convert';

import 'package:web_socket_channel/io.dart';
import 'package:web_socket_channel/status.dart' as status;


class Client {
    String url;
    IOWebSocketChannel channel;
    StreamController<MetricDataPoint> _metricsController = StreamController.broadcast();
    Stream<MetricDataPoint> get metrics => _metricsController.stream;

    Client(this.url);

    open() {
        channel = IOWebSocketChannel.connect(this.url);
        int tick = 1;
        channel.stream.listen((message) {
            Map data = json.decode(message);
            Map commands = data['commands'];
            _metricsController.add(
                MetricDataPoint(
                    tick,
                    CommandMetrics.from_map(commands['search'] ?? {}),
                    CommandMetrics.from_map(commands['resolve'] ?? {})
                )
            );
            tick++;
        });
    }

    Future close() => channel.sink.close(status.goingAway);
}


class CommandMetrics {
    final int started;
    final int finished;
    final int total_time;
    final int execution_time;
    final int query_time;
    final int query_count;
    final int avg_wait_time;
    final int avg_total_time;
    final int avg_execution_time;
    final int avg_query_time_per_search;
    final int avg_query_time_per_query;
    CommandMetrics(
        this.started, this.finished, this.total_time,
        this.execution_time, this.query_time, this.query_count):
        avg_wait_time=finished > 0 ? ((total_time - (execution_time + query_time))/finished).round() : 0,
        avg_total_time=finished > 0 ? (total_time/finished).round() : 0,
        avg_execution_time=finished > 0 ? (execution_time/finished).round() : 0,
        avg_query_time_per_search=finished > 0 ? (query_time/finished).round() : 0,
        avg_query_time_per_query=query_count > 0 ? (query_time/query_count).round() : 0;
    CommandMetrics.from_map(Map data): this(
        data['started'] ?? 0,
        data['finished'] ?? 0,
        data['total_time'] ?? 0,
        data['execution_time'] ?? 0,
        data['query_time'] ?? 0,
        data['query_count'] ?? 0,
    );
}


class MetricDataPoint {
    final int tick;
    final CommandMetrics search;
    final CommandMetrics resolve;
    MetricDataPoint(this.tick, this.search, this.resolve);
    MetricDataPoint.empty():
        tick = 0,
        search=CommandMetrics.from_map({}),
        resolve=CommandMetrics.from_map({});
}


cli() {
    Client('ws://localhost:8181/')..open()..metrics.listen((m) {
        print(m.search);
    });
}
