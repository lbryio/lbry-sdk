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
            var data = json.decode(message);
            print(data);
            _loadDataController.add(
                ServerLoadDataPoint.from_map(
                    tick, data
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


class TimeStats {
    final int avg, min, max;
    // percentiles
    final int five;
    final int twenty_five;
    final int fifty;
    final int seventy_five;
    final int ninety_five;
    TimeStats(
        this.avg, this.min, this.five, this.twenty_five,
        this.fifty, this.seventy_five, this.ninety_five,
        this.max
    );
    TimeStats.from_list(List l): this(
        l[0], l[1], l[2], l[3], l[4], l[5], l[6], l[7]
    );
    TimeStats.from_zeros(): this(
        0, 0, 0, 0, 0, 0, 0, 0
    );
    factory TimeStats.from_list_or_zeros(List l) =>
        l != null ? TimeStats.from_list(l): TimeStats.from_zeros();
}


class APICallMetrics {
    // total requests received
    final int receive_count;
    // sum of these is total responses made
    final int cache_response_count;
    final int query_response_count;
    final int intrp_response_count;
    final int error_response_count;
    // stacked values for chart
    final int cache_response_stack;
    final int query_response_stack;
    final int intrp_response_stack;
    final int error_response_stack;
    // millisecond timings for non-cache responses
    final TimeStats response;
    final TimeStats interrupt;
    final TimeStats error;
    // response, interrupt and error each also report the python, wait and sql stats:
    final TimeStats python;
    final TimeStats wait;
    final TimeStats sql;
    // extended timings for individual sql executions
    final TimeStats individual_sql;
    final int individual_sql_count;
    // actual queries
    final List<String> errored_queries;
    final List<String> interrupted_queries;
    APICallMetrics(
        this.receive_count,
        this.cache_response_count, this.query_response_count,
        this.intrp_response_count, this.error_response_count,
        this.response, this.interrupt, this.error,
        this.python, this.wait, this.sql,
        this.individual_sql, this.individual_sql_count,
        this.errored_queries, this.interrupted_queries
    ):
        cache_response_stack=cache_response_count+query_response_count+intrp_response_count+error_response_count,
        query_response_stack=query_response_count+intrp_response_count+error_response_count,
        intrp_response_stack=intrp_response_count+error_response_count,
        error_response_stack=error_response_count;
    APICallMetrics.from_map(Map data): this(
        data["receive_count"] ?? 0,
        data["cache_response_count"] ?? 0,
        data["query_response_count"] ?? 0,
        data["intrp_response_count"] ?? 0,
        data["error_response_count"] ?? 0,
        TimeStats.from_list_or_zeros(data["response"]),
        TimeStats.from_list_or_zeros(data["interrupt"]),
        TimeStats.from_list_or_zeros(data["error"]),
        TimeStats.from_list_or_zeros(data["python"]),
        TimeStats.from_list_or_zeros(data["wait"]),
        TimeStats.from_list_or_zeros(data["sql"]),
        TimeStats.from_list_or_zeros(data["individual_sql"]),
        data["individual_sql_count"] ?? 0,
        List<String>.from(data["errored_queries"] ?? const []),
        List<String>.from(data["interrupted_queries"] ?? const []),
    );
}


class ServerLoadDataPoint {
    final int tick;
    final int sessions;
    final APICallMetrics search;
    final APICallMetrics resolve;
    const ServerLoadDataPoint(
        this.tick, this.sessions, this.search, this.resolve
    );
    ServerLoadDataPoint.from_map(int tick, Map data): this(
        tick, (data['status'] ?? const {})['sessions'] ?? 0,
        APICallMetrics.from_map((data['api'] ?? const {})['search'] ?? const {}),
        APICallMetrics.from_map((data['api'] ?? const {})['resolve'] ?? const {})
    );
    ServerLoadDataPoint.empty(): this(
        0, 0, APICallMetrics.from_map(const {}), APICallMetrics.from_map(const {})
    );
}


connect_and_listen_for_load_data() {
    ServerConnection(url: 'ws://localhost:8181/')..open()..load_data.listen((m) {
        print(m.search);
    });
}
