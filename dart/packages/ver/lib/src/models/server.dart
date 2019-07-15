import 'dart:async';
import 'dart:collection';
import 'package:flutter/foundation.dart';
import 'package:lbry/lbry.dart';


class ServerManager extends ChangeNotifier {
    final List<Server> _servers = [];
    UnmodifiableListView<Server> get items => UnmodifiableListView(_servers);

    add(Server server) {
        _servers.add(server);
        notifyListeners();
    }

    remove(Server server) {
        server.dispose();
        _servers.remove(server);
        notifyListeners();
    }

    @override
    void dispose() {
        super.dispose();
        for (var server in _servers) {
            server.dispose();
        }
    }

}


class Server extends ChangeNotifier {

    String _label = "";
    String get label => _label;
    String get labelOrHost => _label.length > 0 ? _label : host;

    String _host = "";
    String get host => _host;
    int _port = 8181;
    int get port => _port;
    bool _ssl = false;
    bool get ssl => _ssl;
    String get url => _connection.url;
    _setURL(String host, int port, bool ssl) {
        _host = host;
        _port = port;
        _connection.url = "ws${ssl?'s':''}://$host:$port";
    }

    DateTime _added = new DateTime.now();
    String get added => _added.toIso8601String();

    bool _isDefault = false;
    bool get isDefault => _isDefault;

    bool _isEnabled = false;
    bool get isEnabled => _isEnabled;

    bool _isTrackingServerLoad = false;
    bool get isTrackingServerLoad => _isTrackingServerLoad;
    _setIsTrackingServerLoad(bool toggle_tracking) {
        if (_isTrackingServerLoad && !toggle_tracking) {
            _connection.unsubscribe_from_server_load_data();
        } else if (!_isTrackingServerLoad && toggle_tracking) {
            _connection.subscribe_to_server_load_data();
        }
        _isTrackingServerLoad = toggle_tracking;
    }

    ClientLoadManager clientLoadManager;

    final ServerConnection _connection = ServerConnection();
    bool get isConnected => _connection.isConnected;
    Stream<ServerLoadDataPoint> get serverLoadStream => _connection.load_data;
    final List<ServerLoadDataPoint> serverLoadData = [ServerLoadDataPoint.empty()];

    Server() {
        clientLoadManager = ClientLoadManager(this);
        serverLoadStream.listen(serverLoadData.add);
    }

    update({String host, int port, bool ssl, String label,
            bool isDefault, bool isEnabled, bool isTrackingServerLoad}) {
        if (host != null && port != null && ssl != null) {
            _setURL(host, port, ssl);
        }
        if (isTrackingServerLoad != null) {
            _setIsTrackingServerLoad(isTrackingServerLoad);
        }
        _label = label ?? _label;
        _isDefault = isDefault ?? _isDefault;
        _isEnabled = isEnabled ?? _isEnabled;
        notifyListeners();
    }

    connect() async {
        await _connection.open();
        if (_isTrackingServerLoad) {
            _connection.subscribe_to_server_load_data();
        }
        notifyListeners();
    }

    disconnect() {
        clientLoadManager.stop();
        _connection.close();
        notifyListeners();
    }

    @override
    void dispose() {
        disconnect();
        super.dispose();
    }

}


class ClientLoadManager extends ChangeNotifier {
    final Server _server;

    ClientLoadGenerator clientLoadGenerator;
    final StreamController<ClientLoadDataPoint> _loadDataController = StreamController.broadcast();
    Stream<ClientLoadDataPoint> get clientLoadStream => _loadDataController.stream;
    final List<ClientLoadDataPoint> clientLoadData = [ClientLoadDataPoint.empty()];

    int _load = 1;
    int get load => _load;
    int _offset = 0;
    int get offset => _offset;
    bool _noTotals = false;
    bool get noTotals => _noTotals;

    ClientLoadManager(this._server) {
        clientLoadStream.listen(clientLoadData.add);
    }

    update({int load, int offset, bool noTotals}) {
        _load = load ?? _load;
        _offset = offset ?? _offset;
        _noTotals = noTotals ?? _noTotals;
        notifyListeners();
    }

    start() {
        clientLoadData.clear();
        clientLoadData.add(ClientLoadDataPoint.empty());
        clientLoadGenerator = ClientLoadGenerator(
            _server.host, _server.port,
            query: {
                'id': 1,
                'method': 'blockchain.claimtrie.search',
                'params': {
                    'no_totals': _noTotals,
                    'offset': _offset,
                    'limit': 20,
                    'fee_amount': '<1',
                    //'all_tags': ['funny'],
                    'any_tags': [
                        'crypto',
                        'outdoors',
                        'cars',
                        'automotive'
                    ]
                }
            }, tickCallback: (t, stats) {
                _loadDataController.add(stats);
                //increase = max(1, min(100, increase+2)-stats.backlog);
                //increase += 1;
                //t.query['params']['offset'] = (increase/2).ceil()*t.query['params']['limit'];
                t.load = _load;//rand.nextInt(10)+5;
                return true;
            })..start();
    }

    stop() {
        if (clientLoadGenerator != null) {
            clientLoadGenerator.stop();
        }
    }

    @override
    void dispose() {
        super.dispose();
        stop();
    }

}
