import xmlrpclib


def main():
    daemon = xmlrpclib.ServerProxy("http://localhost:7080/")
    try:
        status = daemon.is_running()
    except:
        status = False

    if status:
        daemon.stop()
        print "LBRYnet daemon stopped"
    else:
        print "LBRYnet daemon wasn't running"

if __name__ == '__main__':
    main()