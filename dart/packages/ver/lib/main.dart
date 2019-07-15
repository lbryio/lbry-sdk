import 'package:flutter/material.dart';
import 'package:flutter/foundation.dart' show debugDefaultTargetPlatformOverride;
import 'package:provider/provider.dart';
import 'package:ver/src/servers.dart';
import 'package:ver/src/models/server.dart';
import 'package:ver/utils.dart';


class UnderConstructionPage extends StatelessWidget {
    @override
    Widget build(BuildContext context) {
        return Scaffold(
            appBar: AppBar(title: Text('Under Construction')),
            body: SizedBox.expand(
                child:  Center(child: Text('Under Construction')),
            ),
        );
    }
}


class MainPage extends StatefulWidget {
    @override
    _MainPageState createState() => _MainPageState();
}


class _MainPageState extends State<MainPage> {
    int _currentIndex = 3;

    @override
    Widget build(BuildContext context) {
        return Scaffold(
            body: IndexedStack(
                index: _currentIndex,
                children: [
                    UnderConstructionPage(),
                    UnderConstructionPage(),
                    UnderConstructionPage(),
                    ServersSectionNavigation(),
                    UnderConstructionPage(),
                ],
            ),
            bottomNavigationBar: BottomNavigationBar(
                items: const <BottomNavigationBarItem>[
                    BottomNavigationBarItem(icon: Icon(Icons.home), title: Text('Home')),
                    BottomNavigationBarItem(icon: Icon(Icons.trending_up), title: Text('Trending')),
                    BottomNavigationBarItem(icon: Icon(Icons.subscriptions), title: Text('Subscriptions')),
                    BottomNavigationBarItem(icon: Icon(Icons.router), title: Text('Servers')),
                    BottomNavigationBarItem(icon: Icon(Icons.folder), title: Text('Library')),
                ],
                currentIndex: _currentIndex,
                onTap: (int index) {
                    setState(() {
                        _currentIndex = index;
                    });
                },
                selectedItemColor: Colors.amber[800],
            ),
        );
    }
}

void main() {
    debugDefaultTargetPlatformOverride = getTargetPlatformForDesktop();
    runApp(
        MaterialApp(
            title: 'Ver',
            theme: ThemeData(
                brightness: Brightness.dark,
                //primarySwatch: Colors.lightBlue,
                fontFamily: 'Roboto',
            ),
            home: MultiProvider(
                providers: [
                    ChangeNotifierProvider<ServerManager>(builder: (context) => ServerManager())
                ],
                child: MainPage()
            )
        )
    );
}
