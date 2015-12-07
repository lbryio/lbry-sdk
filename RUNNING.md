How to watch It's a Wonderful Life via LBRY

## Quickest quick guide

Create a directory called lbry, and go into that directory

Download the file https://raw.githubusercontent.com/lbryio/lbry-setup/master/lbry_setup.sh and run it in that directory

Once it's done building, type:

```
./lbrycrd/src/lbrycrdd -server -daemon
lbrynet-gui
```

A window should show up with an entry box

Type wonderfullife into the box, hit go, and choose to stream or save

To stop lbrycrdd: `./lbrycrd/src/lbrycrd-cli stop`


## Slightly longer install guide

### Installing lbrycrd from source

```
git clone --depth=1 https://github.com/lbryio/lbrycrd.git
cd lbrycrd
sudo apt-get install build-essential libtool autotools-dev autoconf pkg-config libssl-dev libboost-all-dev libdb-dev libdb++-dev libqt4-dev libprotobuf-dev protobuf-compiler
./autogen.sh
./configure --with-incompatible-bdb --without-gui

make
```

When make has completed, create the directory where LBRYcrd data will be stored. ~/.lbrycrd is where LBRYcrd will look by default and so is recommended.

```
mkdir ~/.lbrycrd
echo 'rpcuser=rpcuser
rpcpassword=rpcpassword' > ~/.lbrycrd/lbrycrd.conf
# (use a long random password if your computer is on a network anyone else has access to. e.g, pwgen -s 20)
cd ..

```

### Installing lbrynet from source

Acquire the LBRYnet source code from https://github.com/lbryio/lbry

```
cd lbry
sudo apt-get install libgmp3-dev build-essential python-dev python-pip
```

(with virtualenv)

```
python-virtualenv

virtualenv .

source bin/activate

python setup.py install

```

to deactivate the virtualenv later:

```
deactivate
```

to reactivate it, go to the directory in which you created it and:

```
source bin/activate
```

(without virtualenv)

```
python setup.py build bdist_egg

sudo python setup.py install
```

## Slightly longer running guide

###In order to use lbrynet-console or lbrynet-gui, lbyrcrd must be running.

### Running lbrycrd

If you ran the easy install script, the lbrycrd folder will be in the directory you ran lbry_setup.sh from. Otherwise it is the root of the cloned lbrycrd repository. Go to that directory.

```
./src/lbrycrdd -server -daemon
```

If you want to mine LBC, also use the flag '-gen', so:

```
./src/lbrycrdd -server -daemon -gen
```

It will take a few minutes for your client to download the whole block chain.

lbrycrdd must be running in order for lbrynet to function.

To shut lbrycrdd down: from the lbrycrd directory, run

```
./src/lbrycrd-cli stop
```

### Option 1) Running lbrynet-console

If you used the virtualenv instructions above, make sure the virtualenv is still active. If not, reactivate it according to the instructions above, under "Installing lbrynet from source"

In your terminal: `lbrynet-console`

You should be presented with a prompt.

Watch It's a Wonderful Life via LBRY

Type into the prompt: `get wonderfullife`

To shut it down, press ctrl-c at any time or enter `exit` into the prompt.

### Option 2) Running lbrynet-gui

If you used the virtualenv instructions above, make sure the virtualenv is still active. If not, reactivate it according to the instructions above, under "Installing lbrynet from source"

In your terminal: `lbrynet-gui`

A window should pop up with an entry box. Type `wonderfullife` into the box, hit go, and then choose to save it or stream it.
Enjoy!

Any questions or problems, email jimmy@lbry.io
