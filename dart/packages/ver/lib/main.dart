import 'package:flutter/material.dart';
import 'package:flutter/foundation.dart' show debugDefaultTargetPlatformOverride;
import 'package:ver/utils.dart';
import 'package:ver/time_series_chart.dart';


class VerApp extends StatelessWidget {
  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Ver',
      theme: ThemeData(
          brightness: Brightness.light,
          primarySwatch: Colors.lightBlue,
          fontFamily: 'Roboto',
      ),
      home: VerHomePage(title: 'Wallet Server'),
    );
  }
}


class VerHomePage extends StatefulWidget {
  VerHomePage({Key key, this.title}) : super(key: key);
  final String title;
  @override
  _VerHomePageState createState() => _VerHomePageState();
}

class _VerHomePageState extends State<VerHomePage> {
  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: Text(widget.title),
      ),
      body: new Padding(
        padding: const EdgeInsets.all(8.0),
        child: SimpleTimeSeriesChart()
      ),
    );
  }
}


void main() {
  debugDefaultTargetPlatformOverride = getTargetPlatformForDesktop();
  runApp(new VerApp());
}
