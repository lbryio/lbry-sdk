import time

from torba.server import util


def sessions_lines(data):
    '''A generator returning lines for a list of sessions.

    data is the return value of rpc_sessions().'''
    fmt = ('{:<6} {:<5} {:>17} {:>5} {:>5} {:>5} '
           '{:>7} {:>7} {:>7} {:>7} {:>7} {:>9} {:>21}')
    yield fmt.format('ID', 'Flags', 'Client', 'Proto',
                     'Reqs', 'Txs', 'Subs',
                     'Recv', 'Recv KB', 'Sent', 'Sent KB', 'Time', 'Peer')
    for (id_, flags, peer, client, proto, reqs, txs_sent, subs,
         recv_count, recv_size, send_count, send_size, time) in data:
        yield fmt.format(id_, flags, client, proto,
                         '{:,d}'.format(reqs),
                         '{:,d}'.format(txs_sent),
                         '{:,d}'.format(subs),
                         '{:,d}'.format(recv_count),
                         '{:,d}'.format(recv_size // 1024),
                         '{:,d}'.format(send_count),
                         '{:,d}'.format(send_size // 1024),
                         util.formatted_time(time, sep=''), peer)


def groups_lines(data):
    '''A generator returning lines for a list of groups.

    data is the return value of rpc_groups().'''

    fmt = ('{:<6} {:>9} {:>9} {:>6} {:>6} {:>8}'
           '{:>7} {:>9} {:>7} {:>9}')
    yield fmt.format('ID', 'Sessions', 'Bwidth KB', 'Reqs', 'Txs', 'Subs',
                     'Recv', 'Recv KB', 'Sent', 'Sent KB')
    for (id_, session_count, bandwidth, reqs, txs_sent, subs,
         recv_count, recv_size, send_count, send_size) in data:
        yield fmt.format(id_,
                         '{:,d}'.format(session_count),
                         '{:,d}'.format(bandwidth // 1024),
                         '{:,d}'.format(reqs),
                         '{:,d}'.format(txs_sent),
                         '{:,d}'.format(subs),
                         '{:,d}'.format(recv_count),
                         '{:,d}'.format(recv_size // 1024),
                         '{:,d}'.format(send_count),
                         '{:,d}'.format(send_size // 1024))


def peers_lines(data):
    '''A generator returning lines for a list of peers.

    data is the return value of rpc_peers().'''
    def time_fmt(t):
        if not t:
            return 'Never'
        return util.formatted_time(now - t)

    now = time.time()
    fmt = ('{:<30} {:<6} {:>5} {:>5} {:<17} {:>4} '
           '{:>4} {:>8} {:>11} {:>11} {:>5} {:>20} {:<15}')
    yield fmt.format('Host', 'Status', 'TCP', 'SSL', 'Server', 'Min',
                     'Max', 'Pruning', 'Last Good', 'Last Try',
                     'Tries', 'Source', 'IP Address')
    for item in data:
        features = item['features']
        hostname = item['host']
        host = features['hosts'][hostname]
        yield fmt.format(hostname[:30],
                         item['status'],
                         host.get('tcp_port') or '',
                         host.get('ssl_port') or '',
                         features['server_version'] or 'unknown',
                         features['protocol_min'],
                         features['protocol_max'],
                         features['pruning'] or '',
                         time_fmt(item['last_good']),
                         time_fmt(item['last_try']),
                         item['try_count'],
                         item['source'][:20],
                         item['ip_addr'] or '')
