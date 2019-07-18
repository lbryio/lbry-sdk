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
            SizedBox(height: 300.0, child: APILoadChart(
                server, "Search", (ServerLoadDataPoint dataPoint) => dataPoint.search
            )),
            //SizedBox(height: 300.0, child: APILoadChart(
            //    server, "Resolve", (ServerLoadDataPoint dataPoint) => dataPoint.resolve
            //)),
            SizedBox(height: 300.0, child: ServerPerformanceChart(server)),
            //SizedBox(height: 220.0, child: ClientLoadChart(server.clientLoadManager)),
            //SizedBox(height: 220.0, child: ClientPerformanceChart(server.clientLoadManager)),
        ]);
    }
}


typedef APICallMetrics APIGetter(ServerLoadDataPoint dataPoint);

class APILoadChart extends StatefulWidget {
    final Server server;
    final String name;
    final APIGetter getter;
    APILoadChart(this.server, this.name, this.getter);

    @override
    State<StatefulWidget> createState() => APILoadChartState();
}


class APILoadChartState extends State<APILoadChart> {

    List<charts.Series<ServerLoadDataPoint, int>> seriesData;

    @override
    void initState() {
        super.initState();
        seriesData = [
            /*
            charts.Series<ServerLoadDataPoint, int>(
                id: 'Received',
                colorFn: (_, __) => charts.MaterialPalette.blue.shadeDefault.lighter,
                strokeWidthPxFn: (_, __) => 4.0,
                domainFn: (ServerLoadDataPoint load, _) => load.tick,
                measureFn: (ServerLoadDataPoint load, _) => widget.getter(load).receive_count,
                data: widget.server.serverLoadData,
            ),*/
            charts.Series<ServerLoadDataPoint, int>(
                id: 'Cache',
                colorFn: (_, __) =>
                charts.MaterialPalette.green.shadeDefault,
                domainFn: (ServerLoadDataPoint load, _) => load.tick,
                measureFn: (ServerLoadDataPoint load, _) => widget.getter(load).cache_response_stack,
                data: widget.server.serverLoadData,
            ),
            charts.Series<ServerLoadDataPoint, int>(
                id: 'Query',
                colorFn: (_, __) =>
                charts.MaterialPalette.blue.shadeDefault,
                domainFn: (ServerLoadDataPoint load, _) => load.tick,
                measureFn: (ServerLoadDataPoint load, _) => widget.getter(load).query_response_stack,
                data: widget.server.serverLoadData,
            ),
            charts.Series<ServerLoadDataPoint, int>(
                id: 'Interrupts',
                colorFn: (_, __) => charts.MaterialPalette.red.shadeDefault.lighter,
                domainFn: (ServerLoadDataPoint load, _) => load.tick,
                measureFn: (ServerLoadDataPoint load, _) => widget.getter(load).intrp_response_stack,
                data: widget.server.serverLoadData,
            ),
            charts.Series<ServerLoadDataPoint, int>(
                id: 'Errors',
                colorFn: (_, __) => charts.MaterialPalette.red.shadeDefault,
                domainFn: (ServerLoadDataPoint load, _) => load.tick,
                measureFn: (ServerLoadDataPoint load, _) => widget.getter(load).error_response_stack,
                data: widget.server.serverLoadData,
            ),
            /*
            charts.Series<ServerLoadDataPoint, int>(
                id: '${widget.name} Interrupted',
                colorFn: (_, __) =>
                charts.MaterialPalette.pink.shadeDefault.lighter,
                domainFn: (ServerLoadDataPoint load, _) => load.tick,
                measureFn: (ServerLoadDataPoint load, _) => widget.getter(load).interrupted,
                strokeWidthPxFn: (ServerLoadDataPoint load, _) => 5.0,
                data: widget.server.serverLoadData,
            ),
            charts.Series<ServerLoadDataPoint, int>(
                id: '${widget.name} Errored',
                colorFn: (_, __) =>
                charts.MaterialPalette.red.shadeDefault.darker,
                domainFn: (ServerLoadDataPoint load, _) => load.tick,
                measureFn: (ServerLoadDataPoint load, _) => widget.getter(load).errored,
                strokeWidthPxFn: (ServerLoadDataPoint load, _) => 5.0,
                data: widget.server.serverLoadData,
            ),
            charts.Series<ServerLoadDataPoint, int>(
                id: '${widget.name} From Cache',
                colorFn: (_, __) => charts.MaterialPalette.green.shadeDefault.darker,
                domainFn: (ServerLoadDataPoint load, _) => load.tick,
                measureFn: (ServerLoadDataPoint load, _) => widget.getter(load).cache_hits,
                strokeWidthPxFn: (ServerLoadDataPoint load, _) => 3.0,
                data: widget.server.serverLoadData,
            ),
             */
        ];
    }

    @override
    Widget build(BuildContext context) {
        return StreamBuilder<ServerLoadDataPoint>(
            stream: widget.server.serverLoadStream,
            builder: (BuildContext context, _) => BetterLineChart(seriesData,
                //renderer: new charts.LineRendererConfig<num>(includeArea: true)
            )
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
                id: 'Waiting 95 Percentile',
                colorFn: (_, __) => charts.MaterialPalette.red.shadeDefault.lighter,
                domainFn: (ServerLoadDataPoint load, _) => load.tick,
                measureFn: (ServerLoadDataPoint load, _) => load.search.wait.ninety_five,
                data: widget.server.serverLoadData,
            ),
            charts.Series<ServerLoadDataPoint, int>(
                id: 'Avg. Waiting',
                colorFn: (_, __) => charts.MaterialPalette.red.shadeDefault.darker,
                domainFn: (ServerLoadDataPoint load, _) => load.tick,
                measureFn: (ServerLoadDataPoint load, _) => load.search.wait.avg,
                data: widget.server.serverLoadData,
            ),
            charts.Series<ServerLoadDataPoint, int>(
                id: 'Avg. Executing',
                colorFn: (_, __) => charts.MaterialPalette.teal.shadeDefault.darker,
                domainFn: (ServerLoadDataPoint load, _) => load.tick,
                measureFn: (ServerLoadDataPoint load, _) => load.search.python.avg,
                data: widget.server.serverLoadData,
            ),
            charts.Series<ServerLoadDataPoint, int>(
                id: 'SQLite 95 Percentile',
                colorFn: (_, __) => charts.MaterialPalette.blue.shadeDefault.lighter,
                domainFn: (ServerLoadDataPoint load, _) => load.tick,
                measureFn: (ServerLoadDataPoint load, _) => load.search.sql.ninety_five,
                data: widget.server.serverLoadData,
            ),
            charts.Series<ServerLoadDataPoint, int>(
                id: 'Avg. SQLite',
                colorFn: (_, __) => charts.MaterialPalette.blue.shadeDefault.darker,
                domainFn: (ServerLoadDataPoint load, _) => load.tick,
                measureFn: (ServerLoadDataPoint load, _) => load.search.sql.avg,
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

    BetterLineChart(List<charts.Series<dynamic, int>> seriesList, {charts.LineRendererConfig renderer}):
            itemCount = seriesList[0].data.length,
            lastItem = seriesList[0].data.last,
            super(
                seriesList,
                animate: false,
                defaultRenderer: renderer,
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
