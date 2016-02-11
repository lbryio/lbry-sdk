import xmlrpclib


def main():
    daemon = xmlrpclib.ServerProxy("http://localhost:7080/")
    try:
        b = daemon.get_balance()
        is_running = True
    except:
        is_running = False

    if is_running:
        daemon.stop()
        print "LBRYnet daemon stopped"
    else:
        print "LBRYnet daemon wasn't running"

if __name__ == '__main__':
    main()