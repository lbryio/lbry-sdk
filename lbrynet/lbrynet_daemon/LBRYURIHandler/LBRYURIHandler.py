import os
import json
import webbrowser
import xmlrpclib, sys


def render_video(path):
    r = r'<center><video src="' + path + r'" controls autoplay width="960" height="720"></center>'
    return r


def main(args):
    if len(args) == 0:
        args.append('lbry://wonderfullife')

    daemon = xmlrpclib.ServerProxy('http://localhost:7080/')

    try:
        b = daemon.get_balance()
        is_running = True
    except:
        webbrowser.open('http://lbry.io/get')
        is_running = False

    if len(args) > 1:
        print 'Too many args', args

    elif is_running:
        if args[0][7:] == 'lbry':
            daemon.render_gui()

        elif args[0][7:] == 'settings':
            r = daemon.get_settings()
            html = "<body>" + json.dumps(r) + "</body>"
            r = daemon.render_html(html)

        else:
            r = daemon.get(args[0][7:])
            print r
            path = r['path']
            if path[0] != '/':
                path = '/' + path

            print path
            filename = path.split('/')[len(path.split('/')) - 1]
            extension = path.split('.')[len(path.split('.')) - 1]

            if extension in ['mp4', 'flv', 'mov']:
                html = render_video(path)
                daemon.render_html(html)

            else:
                webbrowser.open('file://' + str(path))


if __name__ == "__main__":
   main(sys.argv[1:])