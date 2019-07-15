import 'package:flutter/material.dart';
import 'package:ver/src/widgets/server.dart';
import 'package:provider/provider.dart';
import 'models/server.dart';


class ServerListPage extends StatelessWidget {
    @override
    Widget build(BuildContext context) =>
        Scaffold(
            appBar: AppBar(title: Text('Servers')),
            body: ServerList(),
            floatingActionButton: FloatingActionButton(
                child: Icon(Icons.add),
                onPressed: () => Navigator.of(context).pushNamed('/edit', arguments: true),
            )
        );
}


class ServerFormPage extends StatelessWidget {

    final bool creating;
    ServerFormPage(this.creating);

    @override
    Widget build(BuildContext context) =>
        Scaffold(
            appBar: AppBar(title: Text(creating ? 'Add Server' : 'Modify Server')),
            body: ServerForm(creating),
        );
}


class ServerViewPage extends StatelessWidget {
    final Server server;
    ServerViewPage(this.server);

    @override
    Widget build(BuildContext context) =>
        Scaffold(
            appBar: AppBar(title: Text(server.labelOrHost)),
            body: ChangeNotifierProvider<Server>.value(
                value: server,
                child: ServerView()
            )
        );
}


class ServersSectionNavigation extends StatelessWidget {
    @override
    Widget build(BuildContext context) {
        return Navigator(
            onGenerateRoute: (RouteSettings settings) {
                return MaterialPageRoute(
                    settings: settings,
                    builder: (BuildContext context) {
                        switch (settings.name) {
                            case '/':
                                return ServerListPage();
                            case '/edit':
                                return ServerFormPage(settings.arguments);
                            case '/view':
                                return ServerViewPage(settings.arguments);
                        }
                        return ServerListPage();
                    },
                );
            },
        );
    }
}
