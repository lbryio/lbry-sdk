import xmlrpclib
import json
from datetime import datetime
from time import sleep
from slackclient import SlackClient

def get_conf():
    f = open('testbot.conf', 'r')
    token = f.readline().replace('\n', '')
    channel = f.readline().replace('\n', '')
    f.close()
    return token, channel

def test_lbrynet(lbry, slack, channel):
    logfile = open('lbrynet_test_log.txt', 'a')

    try:
        path = lbry.get('testlbrynet')['path']
    except:
        msg = '[' + str(datetime.now()) + '] ! Failed to obtain LBRYnet test file'
        slack.rtm_connect()
        slack.rtm_send_message(channel, msg)
        print msg
        logfile.write(msg + '\n')

    file_name = path.split('/')[len(path.split('/'))-1]

    for n in range(10):
        files = [f for f in lbry.get_lbry_files() if (json.loads(f)['file_name'] == file_name) and json.loads(f)['completed']]
        if files:
            break
        sleep(30)

    if files:
        msg = '[' + str(datetime.now()) + '] LBRYnet download test successful'
        slack.rtm_connect()
        # slack.rtm_send_message(channel, msg)
        print msg
        logfile.write(msg + '\n')

    else:
        msg = '[' + str(datetime.now()) + '] ! Failed to obtain LBRYnet test file'
        slack.rtm_connect()
        slack.rtm_send_message(channel, msg)
        print msg
        logfile.write(msg + '\n')

    lbry.delete_lbry_file('test.jpg')
    logfile.close()

token, channel = get_conf()

sc = SlackClient(token)
sc.rtm_connect()
print 'Connected to slack'
daemon = xmlrpclib.ServerProxy("http://localhost:7080")

while True:
    test_lbrynet(daemon, sc, channel)
    sleep(600)
