"""Bump version and create Github release

This script should be run locally, not on a build server.
"""
import argparse
import contextlib
import os
import re
import subprocess
import sys

import git
import github

import changelog

ROOT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))


def main():
    bumpversion_parts = get_bumpversion_parts()

    parser = argparse.ArgumentParser()
    parser.add_argument("part", choices=bumpversion_parts, help="part of version to bump")
    parser.add_argument("--skip-sanity-checks", action="store_true")
    parser.add_argument("--skip-push", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--confirm", action="store_true")
    args = parser.parse_args()

    if args.dry_run:
        print "DRY RUN. Nothing will be committed/pushed."

    repo = Repo('lbry-app', args.part, ROOT)
    branch = 'master'

    print 'Current version: {}'.format(repo.current_version)
    print 'New version: {}'.format(repo.new_version)

    if not args.confirm and not confirm():
        print "Aborting"
        return 1

    if not args.skip_sanity_checks:
        run_sanity_checks(repo, branch)
    repo.assert_new_tag_is_absent()

    is_rc = re.search('\drc\d+$', repo.new_version) is not None
    # only have a release message for real releases, not for RCs
    release_msg = '' if is_rc else repo.get_unreleased_changelog()

    if args.dry_run:
        print "rc: " + ("yes" if is_rc else "no")
        print "release message: \n" + (release_msg or "  NO MESSAGE FOR RCs")
        return

    gh_token = get_gh_token()
    auth = github.Github(gh_token)
    github_repo = auth.get_repo('lbryio/lbry-app')

    if not is_rc:
        repo.bump_changelog()
    repo.bumpversion()

    new_tag = repo.get_new_tag()
    github_repo.create_git_release(new_tag, new_tag, release_msg, draft=True, prerelease=is_rc)

    if args.skip_push:
        print (
            'Skipping push; you will have to reset and delete tags if '
            'you want to run this script again.'
        )
    else:
        repo.git_repo.git.push(follow_tags=True, recurse_submodules='check')


class Repo(object):
    def __init__(self, name, part, directory):
        self.name = name
        self.part = part
        if not self.part:
            raise Exception('Part required')
        self.directory = directory
        self.git_repo = git.Repo(self.directory)
        self._bumped = False

        self.current_version = self._get_current_version()
        self.new_version = self._get_new_version()
        self._changelog = changelog.Changelog(os.path.join(self.directory, 'CHANGELOG.md'))

    def get_new_tag(self):
        return 'v' + self.new_version

    def get_unreleased_changelog(self):
        return self._changelog.get_unreleased()

    def bump_changelog(self):
        self._changelog.bump(self.new_version)
        with pushd(self.directory):
            self.git_repo.git.add(os.path.basename(self._changelog.path))

    def _get_current_version(self):
        with pushd(self.directory):
            output = subprocess.check_output(
                ['bumpversion', '--dry-run', '--list', '--allow-dirty', self.part])
            return re.search('^current_version=(.*)$', output, re.M).group(1)

    def _get_new_version(self):
        with pushd(self.directory):
            output = subprocess.check_output(
                ['bumpversion', '--dry-run', '--list', '--allow-dirty', self.part])
            return re.search('^new_version=(.*)$', output, re.M).group(1)

    def bumpversion(self):
        if self._bumped:
            raise Exception('Cowardly refusing to bump a repo twice')
        with pushd(self.directory):
            subprocess.check_call(['bumpversion', '--allow-dirty', self.part])
            self._bumped = True

    def assert_new_tag_is_absent(self):
        new_tag = self.get_new_tag()
        tags = self.git_repo.git.tag()
        if new_tag in tags.split('\n'):
            raise Exception('Tag {} is already present in repo {}.'.format(new_tag, self.name))

    def is_behind(self, branch):
        self.git_repo.remotes.origin.fetch()
        rev_list = '{branch}...origin/{branch}'.format(branch=branch)
        commits_behind = self.git_repo.git.rev_list(rev_list, right_only=True, count=True)
        commits_behind = int(commits_behind)
        return commits_behind > 0


def get_bumpversion_parts():
    with pushd(ROOT):
        output = subprocess.check_output([
            'bumpversion', '--dry-run', '--list', '--allow-dirty', 'fake-part',
        ])
    parse_line = re.search('^parse=(.*)$', output, re.M).group(1)
    return tuple(re.findall('<([^>]+)>', parse_line))


def get_gh_token():
    if 'GH_TOKEN' in os.environ:
        return os.environ['GH_TOKEN']
    else:
        print """
Please enter your personal access token. If you don't have one
See https://github.com/lbryio/lbry-app/wiki/Release-Script#generate-a-personal-access-token
for instructions on how to generate one.

You can also set the GH_TOKEN environment variable to avoid seeing this message
in the future"""
        return raw_input('token: ').strip()


def confirm():
    return raw_input('Is this what you want? [y/N] ').strip().lower() == 'y'


def run_sanity_checks(repo, branch):
    if repo.git_repo.is_dirty():
        print 'Cowardly refusing to release a dirty repo'
        sys.exit(1)
    if repo.git_repo.active_branch.name != branch:
        print 'Cowardly refusing to release when not on the {} branch'.format(branch)
        sys.exit(1)
    if repo.is_behind(branch):
        print 'Cowardly refusing to release when behind origin'
        sys.exit(1)
    if not is_custom_bumpversion_version():
        print (
            'Install LBRY\'s fork of bumpversion: '
            'pip install -U git+https://github.com/lbryio/bumpversion.git'
        )
        sys.exit(1)


def is_custom_bumpversion_version():
    try:
        output = subprocess.check_output(['bumpversion', '-v'], stderr=subprocess.STDOUT).strip()
        if output == 'bumpversion 0.5.4-lbry':
            return True
    except (subprocess.CalledProcessError, OSError):
        pass
    return False


@contextlib.contextmanager
def pushd(new_dir):
    previous_dir = os.getcwd()
    os.chdir(new_dir)
    yield
    os.chdir(previous_dir)


if __name__ == '__main__':
    sys.exit(main())
