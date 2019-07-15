import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:provider/provider.dart';
import '../models/server.dart';
import 'time_series_chart.dart';


class ServerList extends StatelessWidget {

    @override
    Widget build(BuildContext context) {
        return Consumer<ServerManager>(
            builder: (_, servers, __) =>
                ListView.builder(
                    itemCount: servers.items.length,
                    itemBuilder: (context, index) =>
                    ChangeNotifierProvider<Server>.value(
                        value: servers.items[index],
                        child: ServerListItem()
                    )
                )
        );
    }

}


class ServerListItem extends StatelessWidget {

    @override
    Widget build(BuildContext context) {
        return Card(
            child: Consumer<Server>(
                builder: (_, server, __) =>
                    ListTile(
                        leading: FlutterLogo(size: 72.0),
                        title: Text(server.labelOrHost),
                        subtitle: Text("${server.url}\nadded ${server.added}"),
                        trailing: Icon(Icons.more_vert),
                        isThreeLine: true,
                        onTap: ()=> Navigator.of(context).pushNamed('/view', arguments: server),
                    )
            )
        );
    }
}


class ServerView extends StatelessWidget {

    @override
    Widget build(BuildContext context) => ServerCharts();
}


class ServerForm extends StatefulWidget {
    final bool creating;

    ServerForm(this.creating);

    @override
    _ServerFormState createState() => _ServerFormState();
}


class _ServerFormState extends State<ServerForm> {

    final _formKey = GlobalKey<FormState>();
    final _formData = {
        'label': '',
        'host': 'localhost',
        'port': 8181,
        'ssl': false,
        'isDefault': true,
        'isEnabled': false,
        'isTrackingServerLoad': false
    };

    @override
    Widget build(BuildContext context) {
        return Form(
            key: _formKey,
            child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: <Widget>[
                    ListTile(title: TextFormField(
                        initialValue: _formData['label'],
                        decoration: const InputDecoration(
                            labelText: 'Label',
                            hintText: 'Optional text to display in server list.'
                        ),
                        onSaved: (value) => _formData['label'] = value,
                    )),
                    ListTile(title: TextFormField(
                        initialValue: _formData['host'],
                        keyboardType: TextInputType.url,
                        inputFormatters: [
                            WhitelistingTextInputFormatter(RegExp(r'[\w\-\.]+'))
                        ],
                        decoration: const InputDecoration(
                            labelText: 'Host Name',
                            hintText: 'Enter the host name of the server.'
                        ),
                        validator: (value) => value.isEmpty ? 'A host name is required.' : null,
                        onSaved: (value) => _formData['host'] = value,
                    )),
                    ListTile(title: TextFormField(
                        initialValue: _formData['port'].toString(),
                        keyboardType: TextInputType.number,
                        inputFormatters: [
                            WhitelistingTextInputFormatter.digitsOnly
                        ],
                        decoration: const InputDecoration(
                            labelText: 'Port',
                            hintText: 'Enter the port of the server.'
                        ),
                        validator: (value) => value.isEmpty ? 'A port is required.' : null,
                        onSaved: (value) => setState(() => _formData['port'] = int.parse(value)),
                    )),
                    SwitchListTile(
                        title: Text('Requires SSL.'),
                        value: _formData['ssl'],
                        onChanged: (value) => setState(() => _formData['ssl'] = value),
                    ),
                    SwitchListTile(
                        title: Text('Use this as your primary and default server.'),
                        value: _formData['isDefault'],
                        onChanged: (value) => setState(() => _formData['isDefault'] = value),
                    ),
                    SwitchListTile(
                        title: Text('Always stay connected.'),
                        value: _formData['isEnabled'],
                        onChanged: (value) => setState(() => _formData['isEnabled'] = value),
                    ),
                    SwitchListTile(
                        title: Text('Track server load.'),
                        value: _formData['isTrackingServerLoad'],
                        onChanged: (value) =>
                            setState(() => _formData['isTrackingServerLoad'] = value),
                    ),
                    ListTile(title: RaisedButton(
                        onPressed: () {
                            if (_formKey.currentState.validate()) {
                                _formKey.currentState.save();
                                var manager = Provider.of<ServerManager>(
                                    context, listen: false
                                );
                                var server = Server();
                                server.update(
                                    label: _formData['label'],
                                    host: _formData['host'],
                                    port: _formData['port'],
                                    ssl: _formData['ssl'],
                                    isDefault: _formData['isDefault'],
                                    isEnabled: _formData['isEnabled'],
                                    isTrackingServerLoad: _formData['isTrackingServerLoad'],
                                );
                                manager.add(server);
                                if (server.isEnabled) {
                                    server.connect();
                                }
                                Navigator.of(context).pop();
                            }
                        },
                        child: Text(widget.creating ? 'Add Server' : 'Update Server'),
                    ),
                    ),
                ],
            ),
        );
    }
}
