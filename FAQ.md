#### Getting LBRY for development

Q: How do I get lbry for command line?

A: In order to run lbry from command line, you need more than the packaged app/deb.

######On OS X

You can install LBRY command line by running `curl -sL https://rawgit.com/lbryio/lbry-setup/master/lbry_setup_osx.sh | sudo bash` in a terminal. This script will install lbrynet and its dependancies, as well as the app.

######On Linux

On Ubuntu or Mint you can install the prerequisites and lbrynet by running

    sudo apt-get install libgmp3-dev build-essential python2.7 python2.7-dev python-pip
    git clone https://github.com/lbryio/lbry.git
    cd lbry
    sudo python setup.py install

#### Using LBRY

Q: How do I run lbry from command line?

A: The command is `lbrynet-daemon`

***********

Q: How do I stop lbry from the command line?

A: You can ctrl-c or run `stop-lbrynet-daemon`

***********

Q: How do I run lbry with lbrycrdd (the blockchain node application)?

A: Start lbry with the --wallet flag set: `lbrynet-daemon --wallet=lbrycrd`

Note: when you change the wallet it is persistant until you specify you want to use another wallet - lbryum - with the --wallet flag again.

***********

Q: Where are all the behind the scenes files?

A: On linux, the relevant directories are `~/.lbrynet`, `~/.lbrycrd`, and `~/.lbryum`, depending on which wallets you've used. On OS X, the folders of interest are `~/Library/Application Support/LBRY`, `~/.lbrycrd` and `~/.lbryum`, also depending on which wallets you've used.

***********

Q: How can I see the log in the console?

A: Run lbry with the --log-to-console flag set: `lbrynet-daemon --log-to-console`

***********

Q: How do I specify a web-UI to use?

A: If the files for the UI you'd like to use are storred locally on your computer, start lbry with the --ui flag: `lbrynet-daemon --ui=/full/path/to/ui/files/root/folder`

Note, once set with the UI flag the given UI will be cached by lbry and used as the default going forward. Also, it will only successfully load a UI if it contains a conforming requirements.txt file to specify required lbrynet and lbryum versions. [Here](https://github.com/lbryio/lbry-web-ui/blob/master/dist/requirements.txt) is an example requirements.txt file.

To reset your ui to pull from lbryio, or to try a UI still in development, run lbry with the --branch flag: `lbrynet=daemon --branch=master`

***********

Q: How do I see the list of API functions I can call, and how do I call them?

A: Here is an example script to get the documentation for the various API calls. To use any of the functions displayed, just provide any specified arguments in a dictionary.

Note: the lbry api can only be used while either the app or lbrynet-daemon command line are running

    import sys
    from jsonrpc.proxy import JSONRPCProxy

    try:
      from lbrynet.conf import API_CONNECTION_STRING
    except:
      print "You don't have lbrynet installed!"
      sys.exit(0)
  
    api = JSONRPCProxy.from_url(API_CONNECTION_STRING)
    if not api.is_running():
      print api.daemon_status()
    else:
      for func in api.help():
        print "%s:\n%s" % (func, api.help({'function': func}))

