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
        channel.stream.listen((message) {
            Map data = json.decode(message);
            _metricsController.add(
                MetricDataPoint()
                    ..search=data['search'] ?? 0
                    ..search_time=data['search_time'] ?? 0
                    ..resolve=data['resolve'] ?? 0
                    ..resolve_time=data['resolve_time'] ?? 0
            );
        });
    }

    Future close() => channel.sink.close(status.goingAway);
}


class MetricDataPoint {
    final DateTime time = DateTime.now();
    int search = 0;
    int search_time = 0;
    int resolve = 0;
    int resolve_time = 0;
    int get avg_search => search_time > 0 ? (search_time/search).round() : 0;
    int get avg_resolve => resolve_time > 0 ? (resolve_time/resolve).round() : 0;
}


cli() {
    Client('ws://localhost:8181/')..open()..metrics.listen((m) {
        print(m.search);
    });
}
