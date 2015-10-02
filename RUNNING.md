How to watch It's a Wonderful Life via LBRY

Quickest quick guide
--------------------

Create a directory called lbry, and go into that directory

Download the file https://raw.githubusercontent.com/lbryio/lbry-setup/master/lbry_setup.sh and run it in that directory

Once it's done building, type:

./lbrycrd/src/lbrycrdd -server -daemon -gen

lbrynet-gui

A window should show up with an entry box

Type wonderfullife into the box, hit go, and choose to stream or save

To stop lbrycrdd:

./lbrycrd/src/lbrycrd-cli stop

Slightly longer install guide
-----------------------------

Acquire the LBRYcrd source code from https://github.com/lbryio/lbrycrd

cd lbrycrd

sudo apt-get install build-essential libtool autotools-dev autoconf pkg-config libssl-dev libboost-all-dev libdb-dev libdb++-dev libqt4-dev libprotobuf-dev protobuf-compiler

./autogen.sh

./configure --with-incompatible-bdb

make

When make has completed, create the directory where LBRYcrd data will be stored. ~/.lbrycrd is where LBRYcrd will look by default and so is recommended.

mkdir ~/.lbrycrd

vim ~/.lbrycrd/lbrycrd.conf

Add the following lines to enable the RPC interface, which will be used by lbrynet-console.

rpcuser=rpcuser

rpcpassword=rpcpassword

(use a long random password if your computer is on a network anyone else has access to)

cd ..

Acquire the LBRYnet source code from https://github.com/lbryio/lbry

cd lbry
sudo apt-get install libgmp3-dev build-essential python-dev python-pip

(with virtualenv)

python-virtualenv

virtualenv .

source bin/activate

python setup.py install

to deactivate the virtualenv later:

deactivate

to reactivate it, go to the directory in which you created it and:

source bin/activate

(without virtualenv)

python setup.py build bdist_egg

sudo python setup.py install

Slightly longer running guide
-----------------------------

In order to use lbrynet, lbyrcrdd must be running.

If you ran the easy install script, the lbrycrd folder will be in the directory you ran lbry_setup.sh from. Otherwise it is the root of the cloned lbrycrd repository. Go to that directory.

./src/lbrycrdd -server -daemon -gen

It will take a few minutes for your client to download the whole block chain.
Once it has caught up, it will start mining coins.

If you don't want to mine, leave off the '-gen' flag.

lbrycrdd must be running in order for lbrynet to function.

To shut lbrycrdd down: from the lbrycrd directory, run

 ./src/lbrycrd-cli stop

Running lbrynet-console

If you used the virtualenv instructions above, make sure the virtualenv is still active. If not, reactivate it according to the instructions above.

In your terminal:

lbrynet-console

You should now be presented with a list of options.

Watch It's a Wonderful Life via LBRY

Choose the option labeled Add a stream from a short name by typing the number next to it and pressing the enter key.

You will be prompted for a name. Type in "wonderfullife" and hit enter. After a few seconds, you will prompted to choose what you want to do with the file. Select the option labeled Stream.

You will be shown some options related to the file which you do not care about. Type 'n' and hit enter.

You will be prompted to choose if you really want to download this file. Type 'y' and hit enter.

To shut it down, type ctrl-c at any time or enter the option to shut down from the main menu.

Running lbrynet-gui
In your terminal:

lbrynet-gui

A window should pop up with an entry box. Type 'wonderfullife' into the box, hit go, and then choose to save it or stream it.
Enjoy!

Any questions or problems, email jimmy@lbry.io