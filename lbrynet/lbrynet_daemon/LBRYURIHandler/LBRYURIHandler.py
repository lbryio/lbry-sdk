import webbrowser
import xmlrpclib, sys


def main(args):
    if len(args) == 0:
        args.append('lbry://wonderfullife')

    daemon = xmlrpclib.ServerProxy('http://localhost:7080/')

    if len(args) > 1:
        print 'Too many args', args

    else:
        daemon.download_name(str(args[0])[7:])
        path = daemon.path_from_name(args[0][7:])[0]['path']
        webbrowser.open('file://' + path)

if __name__ == "__main__":
   main(sys.argv[1:])