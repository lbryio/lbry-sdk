import 'dart:math';
import 'package:flutter/material.dart';
import 'package:charts_flutter/flutter.dart' as charts;
import 'package:charts_flutter/src/base_chart_state.dart' as state;
import 'package:charts_common/common.dart' as common;
import 'package:provider/provider.dart';
import 'package:lbry/lbry.dart';
import '../models/server.dart';


class ServerCharts extends StatelessWidget {
    @override
    Widget build(BuildContext context) {
        var server = Provider.of<Server>(context, listen: false);
        return ListView(children: <Widget>[
            SizedBox(height: 300.0, child: ServerLoadChart(server)),
            SizedBox(height: 300.0, child: ServerPerformanceChart(server)),
            //SizedBox(height: 220.0, child: ClientLoadChart(server.clientLoadManager)),
            //SizedBox(height: 220.0, child: ClientPerformanceChart(server.clientLoadManager)),
        ]);
    }
}


class ServerLoadChart extends StatefulWidget {
    final Server server;
    ServerLoadChart(this.server);

    @override
    State<StatefulWidget> createState() => ServerLoadChartState();
}


class ServerLoadChartState extends State<ServerLoadChart> {

    List<charts.Series<ServerLoadDataPoint, int>> seriesData;

    @override
    void initState() {
        super.initState();
        seriesData = [
            charts.Series<ServerLoadDataPoint, int>(
                id: 'Search Cache',
                colorFn: (_, __) => charts.MaterialPalette.green.shadeDefault.darker,
                domainFn: (ServerLoadDataPoint load, _) => load.tick,
                measureFn: (ServerLoadDataPoint load, _) => load.search.cache_hit,
                data: widget.server.serverLoadData,
            ),
            charts.Series<ServerLoadDataPoint, int>(
                id: 'Search Finish',
                colorFn: (_, __) =>
                charts.MaterialPalette.deepOrange.shadeDefault.darker,
                domainFn: (ServerLoadDataPoint load, _) => load.tick,
                measureFn: (ServerLoadDataPoint load, _) => load.search.finished,
                strokeWidthPxFn: (ServerLoadDataPoint load, _) => 5.0,
                data: widget.server.serverLoadData,
            ),
            charts.Series<ServerLoadDataPoint, int>(
                id: 'Search Start',
                colorFn: (_, __) =>
                charts.MaterialPalette.deepOrange.shadeDefault.lighter,
                domainFn: (ServerLoadDataPoint load, _) => load.tick,
                measureFn: (ServerLoadDataPoint load, _) => load.search.started,
                strokeWidthPxFn: (ServerLoadDataPoint load, _) => 1.0,
                data: widget.server.serverLoadData,
            ),
            charts.Series<ServerLoadDataPoint, int>(
                id: 'Resolve Cache',
                colorFn: (_, __) => charts.MaterialPalette.cyan.shadeDefault.darker,
                domainFn: (ServerLoadDataPoint load, _) => load.tick,
                measureFn: (ServerLoadDataPoint load, _) => load.resolve.cache_hit,
                data: widget.server.serverLoadData,
            ),
            charts.Series<ServerLoadDataPoint, int>(
                id: 'Resolve Finish',
                colorFn: (_, __) => charts.MaterialPalette.teal.shadeDefault.darker,
                domainFn: (ServerLoadDataPoint load, _) => load.tick,
                measureFn: (ServerLoadDataPoint load, _) => load.resolve.finished,
                strokeWidthPxFn: (ServerLoadDataPoint load, _) => 5.0,
                data: widget.server.serverLoadData,
            ),
            charts.Series<ServerLoadDataPoint, int>(
                id: 'Resolve Start',
                colorFn: (_, __) => charts.MaterialPalette.teal.shadeDefault.lighter,
                domainFn: (ServerLoadDataPoint load, _) => load.tick,
                measureFn: (ServerLoadDataPoint load, _) => load.resolve.started,
                strokeWidthPxFn: (ServerLoadDataPoint load, _) => 1.0,
                data: widget.server.serverLoadData,
            ),
        ];
    }

    @override
    Widget build(BuildContext context) {
        return StreamBuilder<ServerLoadDataPoint>(
            stream: widget.server.serverLoadStream,
            builder: (BuildContext context, _) => BetterLineChart(seriesData)
        );
    }
}


class ServerPerformanceChart extends StatefulWidget {
    final Server server;
    ServerPerformanceChart(this.server);

    @override
    State<StatefulWidget> createState() => ServerPerformanceChartState();
}


class ServerPerformanceChartState extends State<ServerPerformanceChart> {

    List<charts.Series<ServerLoadDataPoint, int>> seriesData;

    @override
    void initState() {
        super.initState();
        seriesData = [
            charts.Series<ServerLoadDataPoint, int>(
                id: 'Avg. Waiting',
                colorFn: (_, __) => charts.MaterialPalette.red.shadeDefault.darker,
                domainFn: (ServerLoadDataPoint load, _) => load.tick,
                measureFn: (ServerLoadDataPoint load, _) => load.search.avg_wait_time,
                data: widget.server.serverLoadData,
            ),
            charts.Series<ServerLoadDataPoint, int>(
                id: 'Avg. Executing',
                colorFn: (_, __) => charts.MaterialPalette.teal.shadeDefault.lighter,
                domainFn: (ServerLoadDataPoint load, _) => load.tick,
                measureFn: (ServerLoadDataPoint load, _) => load.search.avg_execution_time,
                data: widget.server.serverLoadData,
            ),
            charts.Series<ServerLoadDataPoint, int>(
                id: 'Avg. SQLite',
                colorFn: (_, __) => charts.MaterialPalette.blue.shadeDefault.darker,
                domainFn: (ServerLoadDataPoint load, _) => load.tick,
                measureFn: (ServerLoadDataPoint load, _) => load.search.avg_query_time_per_search,
                data: widget.server.serverLoadData,
            )
        ];
    }

    @override
    Widget build(BuildContext context) {
        return StreamBuilder<ServerLoadDataPoint>(
            stream: widget.server.serverLoadStream,
            builder: (BuildContext context, _) => BetterLineChart(seriesData)
        );
    }
}




class ClientLoadChart extends StatefulWidget {
    final ClientLoadManager client;
    ClientLoadChart(this.client);

    @override
    State<StatefulWidget> createState() => ClientLoadChartState();
}


class ClientLoadChartState extends State<ClientLoadChart> {

    List<charts.Series<ClientLoadDataPoint, int>> seriesData;

    @override
    void initState() {
        super.initState();
        seriesData = [
            charts.Series<ClientLoadDataPoint, int>(
                id: 'Load',
                colorFn: (_, __) => charts.MaterialPalette.black.darker,
                domainFn: (ClientLoadDataPoint load, _) => load.tick,
                measureFn: (ClientLoadDataPoint load, _) => load.load,
                data: widget.client.clientLoadData,
            ),
            charts.Series<ClientLoadDataPoint, int>(
                id: 'Success',
                colorFn: (_, __) => charts.MaterialPalette.green.shadeDefault,
                domainFn: (ClientLoadDataPoint load, _) => load.tick,
                measureFn: (ClientLoadDataPoint load, _) => load.success,
                data: widget.client.clientLoadData,
            ),
            charts.Series<ClientLoadDataPoint, int>(
                id: 'Backlog',
                colorFn: (_, __) => charts.MaterialPalette.red.shadeDefault,
                domainFn: (ClientLoadDataPoint load, _) => load.tick,
                measureFn: (ClientLoadDataPoint load, _) => load.backlog,
                data: widget.client.clientLoadData,
            ),
            charts.Series<ClientLoadDataPoint, int>(
                id: 'Catch-up',
                colorFn: (_, __) => charts.MaterialPalette.yellow.shadeDefault,
                domainFn: (ClientLoadDataPoint load, _) => load.tick,
                measureFn: (ClientLoadDataPoint load, _) => load.catchup,
                data: widget.client.clientLoadData,
            )
        ];
    }

    @override
    Widget build(BuildContext context) {
        return StreamBuilder<ClientLoadDataPoint>(
            stream: widget.client.clientLoadStream,
            builder: (BuildContext context, _) => BetterLineChart(seriesData)
        );
    }
}


class ClientPerformanceChart extends StatefulWidget {
    final ClientLoadManager client;
    ClientPerformanceChart(this.client);

    @override
    State<StatefulWidget> createState() => ClientPerformanceChartState();
}


class ClientPerformanceChartState extends State<ClientPerformanceChart> {

    List<charts.Series<ClientLoadDataPoint, int>> seriesData;

    @override
    void initState() {
        super.initState();
        seriesData = [
            charts.Series<ClientLoadDataPoint, int>(
                id: 'Avg. Success Time',
                colorFn: (_, __) => charts.MaterialPalette.green.shadeDefault,
                domainFn: (ClientLoadDataPoint load, _) => load.tick,
                measureFn: (ClientLoadDataPoint load, _) => load.avg_success,
                data: widget.client.clientLoadData,
            ),
            charts.Series<ClientLoadDataPoint, int>(
                id: 'Avg. Catch-up Time',
                colorFn: (_, __) => charts.MaterialPalette.yellow.shadeDefault,
                domainFn: (ClientLoadDataPoint load, _) => load.tick,
                measureFn: (ClientLoadDataPoint load, _) => load.avg_catchup,
                data: widget.client.clientLoadData,
            ),
        ];
    }

    @override
    Widget build(BuildContext context) {
        return StreamBuilder<ClientLoadDataPoint>(
            stream: widget.client.clientLoadStream,
            builder: (BuildContext context, _) => BetterLineChart(seriesData)
        );
    }
}


class BetterLineChart extends charts.LineChart {

    final int itemCount;
    final Object lastItem;

    BetterLineChart(List<charts.Series<dynamic, int>> seriesList):
            itemCount = seriesList[0].data.length,
            lastItem = seriesList[0].data.last,
            super(
                seriesList,
                behaviors: [charts.SeriesLegend()],
                domainAxis: charts.NumericAxisSpec(
                    viewport: new charts.NumericExtents(
                        max(0, seriesList[0].data.last.tick - 60), seriesList[0].data.last.tick
                    ),
                    renderSpec: new charts.SmallTickRendererSpec(
                        labelStyle: new charts.TextStyleSpec(
                            color: charts.MaterialPalette.gray.shade50
                        ),
                        lineStyle: new charts.LineStyleSpec(
                            color: charts.MaterialPalette.black
                        )
                    ),
                ),
                primaryMeasureAxis: new charts.NumericAxisSpec(
                    renderSpec: new charts.GridlineRendererSpec(
                        labelStyle: new charts.TextStyleSpec(
                            color: charts.MaterialPalette.white
                        ),
                        lineStyle: new charts.LineStyleSpec(
                            color: charts.MaterialPalette.gray.shade100
                        ),
                    ),
                    tickProviderSpec: new charts.BasicNumericTickProviderSpec(
                        dataIsInWholeNumbers: true,
                        desiredTickCount: 5
                    )
                ),
            );

    @override
    void updateCommonChart(common.BaseChart baseChart, charts.BaseChart oldWidget,
        state.BaseChartState chartState) {
        super.updateCommonChart(baseChart, oldWidget, chartState);
        final prev = oldWidget as BetterLineChart;
        if (itemCount != prev?.itemCount || lastItem != prev?.lastItem) {
            chartState.markChartDirty();
        }
    }

}
