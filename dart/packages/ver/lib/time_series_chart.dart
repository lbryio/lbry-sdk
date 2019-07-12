import 'dart:math';
import 'package:flutter/material.dart';
import 'package:charts_flutter/flutter.dart' as charts;
import 'package:charts_flutter/src/base_chart_state.dart' as state;
import 'package:charts_common/common.dart' as common;
import 'package:lbry/lbry.dart';


class SimpleTimeSeriesChart extends StatefulWidget {
    SimpleTimeSeriesChart({Key key}) : super(key: key);
    @override
    _SimpleTimeSeriesChartState createState() => _SimpleTimeSeriesChartState();
}


class _SimpleTimeSeriesChartState extends State<SimpleTimeSeriesChart> {
    final List<MetricDataPoint> metricData = [];
    final List<LoadDataPoint> loadData = [];
    final List<charts.Series<LoadDataPoint, DateTime>> loadSeries = [];
    final List<charts.Series<LoadDataPoint, DateTime>> timeSeries = [];
    final List<charts.Series<MetricDataPoint, DateTime>> metricSeries = [];
    final List<charts.Series<MetricDataPoint, DateTime>> metricTimeSeries = [];
    final Random rand = Random();
    LoadGenerator loadGenerator;
    Client client;

    @override
    void initState() {
        super.initState();
        metricSeries.add(
            charts.Series<MetricDataPoint, DateTime>(
                id: 'Searches',
                colorFn: (_, __) => charts.MaterialPalette.black.darker,
                domainFn: (MetricDataPoint load, _) => load.time,
                measureFn: (MetricDataPoint load, _) => load.search,
                data: metricData,
            )
        );
        metricSeries.add(
            charts.Series<MetricDataPoint, DateTime>(
                id: 'Resolves',
                colorFn: (_, __) => charts.MaterialPalette.black.darker,
                domainFn: (MetricDataPoint load, _) => load.time,
                measureFn: (MetricDataPoint load, _) => load.resolve,
                data: metricData,
            )
        );
        metricTimeSeries.add(
            charts.Series<MetricDataPoint, DateTime>(
                id: 'Avg. Resolve Time',
                colorFn: (_, __) => charts.MaterialPalette.green.shadeDefault,
                domainFn: (MetricDataPoint load, _) => load.time,
                measureFn: (MetricDataPoint load, _) => load.avg_resolve,
                data: metricData,
            )
        );
        metricTimeSeries.add(
            charts.Series<MetricDataPoint, DateTime>(
                id: 'Avg. Search Time',
                colorFn: (_, __) => charts.MaterialPalette.yellow.shadeDefault,
                domainFn: (MetricDataPoint load, _) => load.time,
                measureFn: (MetricDataPoint load, _) => load.avg_search,
                data: metricData,
            )
        );
        loadSeries.add(
            charts.Series<LoadDataPoint, DateTime>(
                id: 'Load',
                colorFn: (_, __) => charts.MaterialPalette.black.darker,
                domainFn: (LoadDataPoint load, _) => load.time,
                measureFn: (LoadDataPoint load, _) => load.load,
                data: loadData,
            )
        );
        loadSeries.add(
            charts.Series<LoadDataPoint, DateTime>(
                id: 'Success',
                colorFn: (_, __) => charts.MaterialPalette.green.shadeDefault,
                domainFn: (LoadDataPoint load, _) => load.time,
                measureFn: (LoadDataPoint load, _) => load.success,
                data: loadData,
            )
        );
        loadSeries.add(
            charts.Series<LoadDataPoint, DateTime>(
                id: 'Backlog',
                colorFn: (_, __) => charts.MaterialPalette.red.shadeDefault,
                domainFn: (LoadDataPoint load, _) => load.time,
                measureFn: (LoadDataPoint load, _) => load.backlog,
                data: loadData,
            )
        );
        loadSeries.add(
            charts.Series<LoadDataPoint, DateTime>(
                id: 'Catch-up',
                colorFn: (_, __) => charts.MaterialPalette.yellow.shadeDefault,
                domainFn: (LoadDataPoint load, _) => load.time,
                measureFn: (LoadDataPoint load, _) => load.catchup,
                data: loadData,
            )
        );
        timeSeries.add(
            charts.Series<LoadDataPoint, DateTime>(
                id: 'Avg. Success Time',
                colorFn: (_, __) => charts.MaterialPalette.green.shadeDefault,
                domainFn: (LoadDataPoint load, _) => load.time,
                measureFn: (LoadDataPoint load, _) => load.avg_success,
                data: loadData,
            )
        );
        timeSeries.add(
            charts.Series<LoadDataPoint, DateTime>(
                id: 'Avg. Catch-up Time',
                colorFn: (_, __) => charts.MaterialPalette.yellow.shadeDefault,
                domainFn: (LoadDataPoint load, _) => load.time,
                measureFn: (LoadDataPoint load, _) => load.avg_catchup,
                data: loadData,
            )
        );
        var increase = 1;
        loadData.add(LoadDataPoint());
        loadGenerator = LoadGenerator('localhost', 50001, {
                'id': 1,
                'method': 'blockchain.claimtrie.search',
                'params': {
                    'offset': 0,
                    'limit': 20,
                    'fee_amount': '<1',
                    'all_tags': ['funny'],
                    'any_tags': [
                        'crypto',
                        'outdoors',
                        'cars',
                        'automotive'
                    ]
                }
            }, (t, stats) {
            setState(() {
                //if (loadData.length > 60) loadData.removeAt(0);
                loadData.add(stats);
            });
            increase = max(1, min(30, (increase*1.1).ceil())-stats.backlog);
            //increase += 1;
            //t.query['params']['offset'] = (increase/2).ceil()*t.query['params']['limit'];
            t.load = increase;//rand.nextInt(10)+5;
            return true;
        })..start();
        metricData.add(MetricDataPoint());
        client = Client('ws://localhost:8181/')..open()..metrics.listen((m) {
            setState(() {
                metricData.add(m);
            });
            print(m.avg_resolve);
            print(m.avg_search);
        });
    }

    @override
    void dispose() {
      if (client != null) client.close();
      if (loadGenerator != null) loadGenerator.stop();
      super.dispose();
    }

    @override
    Widget build(BuildContext context) {
        return Column(children: <Widget>[
            SizedBox(height: 250.0, child: BetterTimeSeriesChart(loadSeries)),
            SizedBox(height: 250.0, child: BetterTimeSeriesChart(timeSeries)),
            SizedBox(height: 250.0, child: BetterTimeSeriesChart(metricSeries)),
            SizedBox(height: 250.0, child: BetterTimeSeriesChart(metricTimeSeries)),
        ]);
    }

}


class BetterTimeSeriesChart extends charts.TimeSeriesChart {

    final int itemCount;
    final Object lastItem;

    BetterTimeSeriesChart(
        List<charts.Series<dynamic, DateTime>> seriesList):
            itemCount = seriesList[0].data.length,
            lastItem = seriesList[0].data.last,
            super(seriesList, behaviors: [charts.SeriesLegend()]);

    @override
    void updateCommonChart(common.BaseChart baseChart, charts.BaseChart oldWidget,
        state.BaseChartState chartState) {
        super.updateCommonChart(baseChart, oldWidget, chartState);
        final prev = oldWidget as BetterTimeSeriesChart;
        if (itemCount != prev?.itemCount || lastItem != prev?.lastItem) {
            chartState.markChartDirty();
        }
    }

}

