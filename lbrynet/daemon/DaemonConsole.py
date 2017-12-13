# -*- coding: utf-8 -*-

import sys
import code
import argparse
import logging.handlers
from exceptions import SystemExit
from twisted.internet import defer, reactor, threads
from lbrynet import analytics
from lbrynet import conf
from lbrynet.core import utils
from lbrynet.core import log_support
from lbrynet.daemon.DaemonServer import DaemonServer
from lbrynet.daemon.auth.client import LBRYAPIClient
from lbrynet.daemon.Daemon import Daemon

get_client = LBRYAPIClient.get_client

log = logging.getLogger(__name__)


if sys.platform.startswith('darwin') or sys.platform.startswith('linux'):
    def color(msg, c="white"):
        _colors = {
            "normal": (0, 37),
            "underlined": (2, 37),
            "red": (1, 31),
            "green": (1, 32),
            "yellow": (1, 33),
            "blue": (1, 33),
            "magenta": (1, 34),
            "cyan": (1, 35),
            "white": (1, 36),
            "grey": (1, 37)
        }
        i, j = _colors[c]
        return "\033[%i;%i;40m%s\033[0m" % (i, j, msg)


    logo = """\
                            ╓▄█▄ç                           
                        ,▄█▓▓▀▀▀▓▓▓▌▄,                      
                     ▄▄▓▓▓▀¬      ╙▀█▓▓▓▄▄                  
                 ,▄█▓▓▀▀              ^▀▀▓▓▓▌▄,             
              ▄█▓▓█▀`                      ╙▀█▓▓▓▄▄         
          ╓▄▓▓▓▀╙                               ▀▀▓▓▓▌▄,    
       ▄█▓▓█▀                                       ╙▀▓▓    
   ╓▄▓▓▓▀`                                        ▄█▓▓▓▀    
  ▓▓█▀                                        ,▄▓▓▓▀╙       
  ▓▓m   ╟▌▄,                               ▄█▓▓█▀     ,,╓µ  
  ▓▓m   ^▀█▓▓▓▄▄                       ╓▄▓▓▓▀╙     █▓▓▓▓▓▀  
  ▓▓Q       '▀▀▓▓▓▌▄,              ,▄█▓▓█▀       ▄█▓▓▓▓▓▀   
  ▀▓▓▓▌▄,        ╙▀█▓▓█▄╗       ╓▄▓▓▓▀       ╓▄▓▓▓▀▀  ▀▀    
     ╙▀█▓▓█▄╗        ^▀▀▓▓▓▌▄▄█▓▓▀▀       ▄█▓▓█▀`           
         '▀▀▓▓▓▌▄,        ╙▀██▀`      ╓▄▓▓▓▀╙               
              ╙▀█▓▓█▄╥            ,▄█▓▓▀▀                   
                  └▀▀▓▓▓▌▄     ▄▒▓▓▓▀╙                      
                       ╙▀█▓▓█▓▓▓▀▀                          
                           ╙▀▀`                             
                                                            
"""
else:
    def color(msg, c=None):
        return msg

    logo = """\
                     '.                    
                    ++++.                  
                  +++,;+++,                
                :+++    :+++:              
               +++        ,+++;            
             '++;           .+++'          
           `+++               `++++        
          +++.                  `++++      
        ;+++                       ++++    
       +++                           +++   
     +++:                             '+   
   ,+++                              +++   
  +++`                             +++:    
 `+'                             ,+++      
 `+   +                         +++        
 `+   +++                     '++'  :'+++: 
 `+    ++++                 `+++     ++++  
 `+      ++++              +++.     :+++'  
 `+,       ++++          ;+++      +++++   
 `+++,       ++++       +++      +++;  +   
   ,+++,       ++++   +++:     .+++        
     ,+++:       '++++++      +++`         
       ,+++:       '++      '++'           
         ,+++:            `+++             
           .+++;         +++,              
             .+++;     ;+++                
               .+++;  +++                  
                 `+++++:                   
                   `++
                              
"""

welcometext = """\
For a list of available commands:
    >>>help()

To see the documentation for a given command:
    >>>help("resolve")

To exit:
    >>>exit()
"""

welcome = "{:*^60}\n".format(" Welcome to the lbrynet interactive console! ")
welcome += "\n".join(["{:<60}".format(w) for w in welcometext.splitlines()])
welcome += "\n%s" % ("*" * 60)
welcome = color(welcome, "grey")
banner = color(logo, "green") + color(welcome, "grey")


def get_methods(daemon):
    locs = {}

    def wrapped(name, fn):
        client = get_client()
        _fn = getattr(client, name)
        _fn.__doc__ = fn.__doc__
        return {name: _fn}

    for method_name, method in daemon.callable_methods.iteritems():
        locs.update(wrapped(method_name, method))
    return locs


def run_terminal(callable_methods, started_daemon, quiet=False):
    locs = {}
    locs.update(callable_methods)

    def help(method_name=None):
        if not method_name:
            print "Available api functions: "
            for name in callable_methods:
                print "\t%s" % name
            return
        if method_name not in callable_methods:
            print "\"%s\" is not a recognized api function"
            return
        print callable_methods[method_name].__doc__
        return

    locs.update({'help': help})

    if started_daemon:
        def exit(status=None):
            if not quiet:
                print "Stopping lbrynet-daemon..."
            callable_methods['daemon_stop']()
            return sys.exit(status)

        locs.update({'exit': exit})
    else:
        def exit(status=None):
            try:
                reactor.callLater(0, reactor.stop)
            except Exception as err:
                print "error stopping reactor: ", err
            return sys.exit(status)

        locs.update({'exit': exit})

    code.interact(banner if not quiet else "", local=locs)


@defer.inlineCallbacks
def start_server_and_listen(use_auth, analytics_manager, quiet):
    log_support.configure_console()
    logging.getLogger("lbrynet").setLevel(logging.CRITICAL)
    logging.getLogger("lbryum").setLevel(logging.CRITICAL)
    logging.getLogger("requests").setLevel(logging.CRITICAL)

    analytics_manager.send_server_startup()
    daemon_server = DaemonServer(analytics_manager)
    try:
        yield daemon_server.start(use_auth)
        analytics_manager.send_server_startup_success()
        if not quiet:
            print "Started lbrynet-daemon!"
        defer.returnValue(True)
    except Exception as e:
        log.exception('Failed to start lbrynet-daemon')
        analytics_manager.send_server_startup_error(str(e))
        daemon_server.stop()
        raise


def threaded_terminal(started_daemon, quiet):
    callable_methods = get_methods(Daemon)
    d = threads.deferToThread(run_terminal, callable_methods, started_daemon, quiet)
    d.addErrback(lambda err: err.trap(SystemExit))
    d.addErrback(log.exception)


def start_lbrynet_console(quiet, use_existing_daemon, useauth):
    if not utils.check_connection():
        print "Not connected to internet, unable to start"
        raise Exception("Not connected to internet, unable to start")
    if not quiet:
        print "Starting lbrynet-console..."
    try:
        get_client().status()
        d = defer.succeed(False)
        if not quiet:
            print "lbrynet-daemon is already running, connecting to it..."
    except:
        if not use_existing_daemon:
            if not quiet:
                print "Starting lbrynet-daemon..."
            analytics_manager = analytics.Manager.new_instance()
            d = start_server_and_listen(useauth, analytics_manager, quiet)
        else:
            raise Exception("cannot connect to an existing daemon instance, "
                            "and set to not start a new one")
    d.addCallback(threaded_terminal, quiet)
    d.addErrback(log.exception)


def main():
    conf.initialize_settings()
    parser = argparse.ArgumentParser(description="Launch lbrynet-daemon")
    parser.add_argument(
        "--use_existing_daemon",
        help="Start lbrynet-daemon if it isn't already running",
        action="store_true",
        default=False,
        dest="use_existing_daemon"
    )
    parser.add_argument(
        "--quiet", dest="quiet", action="store_true", default=False
    )
    parser.add_argument(
        "--http-auth", dest="useauth", action="store_true", default=conf.settings['use_auth_http']
    )
    args = parser.parse_args()
    start_lbrynet_console(args.quiet, args.use_existing_daemon, args.useauth)
    reactor.run()


if __name__ == "__main__":
    main()
