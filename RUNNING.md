How to watch It's a Wonderful Life via LBRY

## Quickest quick guide

Create a directory called lbry, and go into that directory

Download the file https://raw.githubusercontent.com/lbryio/lbry-setup/master/lbry_setup.sh and run it in that directory

Once it's done building, type:

```
lbrynet-console
```

A console application will load, and after a moment you will be presented with a ">" signifying
that the console is ready for commands.

If it's your first time running lbrynet-console, you should be given some credits to test the
network. If they don't show up within a minute or two, let us know, and we'll send you some.

After your credits have shown up, type

```
get wonderfullife
```

into the prompt and hit enter.

You will be asked if you want to cancel, change options, save, and perhaps stream the file.

Enter 's' for save and then hit enter.

The file should start downloading. Enter the command 'status' to check on the status of files
that are in the process of being downloaded.

To stop lbrynet-console, enter the command 'exit'.


## Slightly longer install guide

### Installing lbrycrd, the full blockchain client

Note: this process takes upwards of an hour and is not necessary to use lbrynet.

```
git clone --depth=1 -b alpha https://github.com/lbryio/lbrycrd.git
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

### lbrynet-console can be set to use lbrycrdd instead of the built in lightweight client.

To run lbrynet-console with lbrycrdd:

```
lbrynet-console </path/to/lbrycrdd>
```

If lbrycrdd is not already running, lbrynet will launch it at that path, and will shut it down
when lbrynet exits. If lbrycrdd is already running, lbrynet will not launch it and will not
shut it down, but it will connect to it and use it.

### Running lbrycrdd manually

From the lbrycrd directory, run:

```
./src/lbrycrdd -server -daemon
```

If you want to mine LBC, also use the flag '-gen', so:

```
./src/lbrycrdd -server -daemon -gen
```

Warning: This will put a heavy load on your CPU

It will take a few minutes for your client to download the whole block chain.

To shut lbrycrdd down: from the lbrycrd directory, run:

```
./src/lbrycrd-cli stop
```

Any questions or problems, email jimmy@lbry.io
