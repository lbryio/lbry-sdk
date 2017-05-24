import glob
import json
import os
import subprocess
import sys

import github
import uritemplate
import boto3

this_dir = os.path.dirname(os.path.realpath(__file__))


def main():
    upload_to_github_if_tagged('lbryio/lbry')
    upload_to_s3('daemon')


def get_asset_filename():
    return glob.glob(this_dir + '/dist/*.zip')[0]


def upload_to_s3(folder):
    tag = subprocess.check_output(['git', 'describe', '--always', 'HEAD']).strip()
    commit_date = subprocess.check_output([
        'git', 'show', '-s', '--format=%cd', '--date=format:%Y%m%d-%H%I%S', 'HEAD']).strip()

    asset_path = get_asset_filename()
    bucket = 'releases.lbry.io'
    key = folder + '/' + commit_date + '-' + tag + '/' + os.path.basename(asset_path)

    print "Uploading " + asset_path + " to s3://" + bucket + '/' + key + ''

    if 'AWS_ACCESS_KEY_ID' not in os.environ or 'AWS_SECRET_ACCESS_KEY' not in os.environ:
        print 'Must set AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY to publish assets to s3'
        return 1

    s3 = boto3.resource(
        's3',
        aws_access_key_id=os.environ['AWS_ACCESS_KEY_ID'],
        aws_secret_access_key=os.environ['AWS_SECRET_ACCESS_KEY'],
        config=boto3.session.Config(signature_version='s3v4')
    )
    s3.meta.client.upload_file(asset_path, bucket, key)


def upload_to_github_if_tagged(repo_name):
    try:
        current_tag = subprocess.check_output(
            ['git', 'describe', '--exact-match', 'HEAD']).strip()
    except subprocess.CalledProcessError:
        print 'Not uploading to GitHub as we are not currently on a tag'
        return 1

    print "Current tag: " + current_tag

    if 'GH_TOKEN' not in os.environ:
        print 'Must set GH_TOKEN in order to publish assets to a release'
        return 1

    gh_token = os.environ['GH_TOKEN']
    auth = github.Github(gh_token)
    repo = auth.get_repo(repo_name)

    if not check_repo_has_tag(repo, current_tag):
        print 'Tag {} is not in repo {}'.format(current_tag, repo)
        # TODO: maybe this should be an error
        return 1

    asset_path = get_asset_filename()
    print "Uploading " + asset_path + " to Github tag " + current_tag
    release = get_github_release(repo, current_tag)
    upload_asset_to_github(release, asset_path, gh_token)


def check_repo_has_tag(repo, target_tag):
    tags = repo.get_tags().get_page(0)
    for tag in tags:
        if tag.name == target_tag:
            return True
    return False


def get_github_release(repo, current_tag):
    for release in repo.get_releases():
        if release.tag_name == current_tag:
            return release
    raise Exception('No release for {} was found'.format(current_tag))


def upload_asset_to_github(release, asset_to_upload, token):
    basename = os.path.basename(asset_to_upload)
    for asset in release.raw_data['assets']:
        if asset['name'] == basename:
            print 'File {} has already been uploaded to {}'.format(basename, release.tag_name)
            return

    upload_uri = uritemplate.expand(release.upload_url, {'name': basename})
    count = 0
    while count < 10:
        try:
            output = _curl_uploader(upload_uri, asset_to_upload, token)
            if 'errors' in output:
                raise Exception(output)
            else:
                print 'Successfully uploaded to {}'.format(output['browser_download_url'])
        except Exception:
            print 'Failed uploading on attempt {}'.format(count + 1)
            count += 1


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


if __name__ == '__main__':
    sys.exit(main())
