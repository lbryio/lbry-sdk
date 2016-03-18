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
        daemon.is_running()

        if len(args) > 1:
            exit(1)

        if args[0][7:] == 'lbry':
            daemon.render_gui()

        elif args[0][7:] == 'settings':
            r = daemon.get_settings()
            html = "<body>" + json.dumps(r) + "</body>"
            daemon.render_html(html)

        else:
            r = daemon.get(args[0][7:])
            path = r['path']
            if path[0] != '/':
                path = '/' + path

            filename = os.path.basename(path)
            extension = os.path.splitext(filename)[1]

            if extension in ['mp4', 'flv', 'mov']:
                html = render_video(path)
                daemon.render_html(html)

            else:
                webbrowser.open('file://' + str(path))

    except:
        webbrowser.open('http://lbry.io/get')


if __name__ == "__main__":
   main(sys.argv[1:])
