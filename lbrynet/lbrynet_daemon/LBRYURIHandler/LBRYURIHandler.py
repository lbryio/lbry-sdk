import os
import webbrowser
import xmlrpclib, sys


def main(args):
    if len(args) == 0:
        args.append('lbry://economicsman')

    daemon = xmlrpclib.ServerProxy('http://localhost:7080/')

    if len(args) > 1:
        print 'Too many args', args

    else:
        resolved = daemon.resolve_name(str(args[0])[7:])
        daemon.download_name(str(args[0])[7:])
        path = [h for h in daemon.get_downloads() if h['stream_hash'] == resolved['stream_hash']][0]['path']
        webbrowser.open('file://' + path)


if __name__ == "__main__":
   main(sys.argv[1:])