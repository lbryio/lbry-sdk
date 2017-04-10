import glob
import json
import os
import subprocess
import sys

import github
import requests
import uritemplate


def main():
    this_dir = os.path.dirname(os.path.realpath(__file__))
    try:
        current_tag = subprocess.check_output(
            ['git', 'describe', '--exact-match', 'HEAD']).strip()
    except subprocess.CalledProcessError:
        print 'Stopping as we are not currently on a tag'
        return

    if 'GH_TOKEN' not in os.environ:
        print 'Must set GH_TOKEN in order to publish assets to a release'
        return

    gh_token = os.environ['GH_TOKEN']
    auth = github.Github(gh_token)
    repo = auth.get_repo('lbryio/lbry')

    if not check_repo_has_tag(repo, current_tag):
        print 'Tag {} is not in repo {}'.format(current_tag, repo)
        # TODO: maybe this should be an error
        return

    daemon_zip = glob.glob(this_dir + '/dist/*.zip')[0]
    release = get_release(repo, current_tag)
    upload_asset(release, daemon_zip, gh_token)


def check_repo_has_tag(repo, target_tag):
    tags = repo.get_tags().get_page(0)
    for tag in tags:
        if tag.name == target_tag:
            return True
    return False


def get_release(current_repo, current_tag):
    for release in current_repo.get_releases():
        if release.tag_name == current_tag:
            return release
    raise Exception('No release for {} was found'.format(current_tag))


def upload_asset(release, asset_to_upload, token):
    basename = os.path.basename(asset_to_upload)
    if is_asset_already_uploaded(release, basename):
        return
    count = 0
    while count < 10:
        try:
            return _upload_asset(release, asset_to_upload, token, _requests_uploader)
        except Exception:
            print 'Failed uploading on attempt {}'.format(count + 1)
            count += 1


def _upload_asset(release, asset_to_upload, token, uploader):
    basename = os.path.basename(asset_to_upload)
    upload_uri = uritemplate.expand(release.upload_url, {'name': basename})
    output = uploader(upload_uri, asset_to_upload, token)
    if 'errors' in output:
        raise Exception(output)
    else:
        print 'Successfully uploaded to {}'.format(output['browser_download_url'])


# requests doesn't work on windows / linux / osx.
def _requests_uploader(upload_uri, asset_to_upload, token):
    print 'Using requests to upload {} to {}'.format(asset_to_upload, upload_uri)
    with open(asset_to_upload, 'rb') as f:
        response = requests.post(upload_uri, data=f, auth=('', token))
    return response.json()


# curl -H "Content-Type: application/json" -X POST -d '{"username":"xyz","password":"xyz"}' http://localhost:3000/api/login


def _curl_uploader(upload_uri, asset_to_upload, token):
    # using requests.post fails miserably with SSL EPIPE errors. I spent
    # half a day trying to debug before deciding to switch to curl.
    #
    # TODO: actually set the content type
    print 'Using curl to upload {} to {}'.format(asset_to_upload, upload_uri)
    cmd = [
        'curl',
        '-sS',
        '-X', 'POST',
        '-u', ':{}'.format(os.environ['GH_TOKEN']),
        '--header', 'Content-Type: application/octet-stream',
        '--data-binary', '@-',
        upload_uri
    ]
    # '-d', '{"some_key": "some_value"}',
    print 'Calling curl:'
    print cmd
    print
    with open(asset_to_upload, 'rb') as fp:
        p = subprocess.Popen(cmd, stdin=fp, stderr=subprocess.PIPE, stdout=subprocess.PIPE)
    stdout, stderr = p.communicate()
    print 'curl return code:', p.returncode
    if stderr:
        print 'stderr output from curl:'
        print stderr
    print 'stdout from curl:'
    print stdout
    return json.loads(stdout)


def is_asset_already_uploaded(release, basename):
    for asset in release.raw_data['assets']:
        if asset['name'] == basename:
            print 'File {} has already been uploaded to {}'.format(basename, release.tag_name)
            return True
    return False


if __name__ == '__main__':
    sys.exit(main())
