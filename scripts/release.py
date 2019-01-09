import os
import re
import io
import sys
import json
import argparse
import unittest
from datetime import date
from getpass import getpass

try:
    import github3
except ImportError:
    print('To run release tool you need to install github3.py:')
    print('')
    print('  $ pip install github3.py')
    print('')
    sys.exit(1)


AREA_RENAME = {
    'api': 'API'
}


def get_github():
    config_path = os.path.expanduser('~/.lbry-release-tool.json')
    if os.path.exists(config_path):
        with open(config_path, 'r') as config_file:
            config = json.load(config_file)
            return github3.login(token=config['token'])
    print('GitHub Credentials')
    username = input('username: ')
    password = getpass('password: ')
    gh = github3.authorize(
        username, password, ['repo'], 'lbry release tool',
        two_factor_callback=lambda: input('Enter 2FA: ')
    )
    with open(config_path, 'w') as config_file:
        json.dump({'token': gh.token}, config_file)
    return github3.login(token=gh.token)


def get_labels(pr, prefix):
    for label in pr.labels:
        label_name = label['name']
        if label_name.startswith(f'{prefix}: '):
            yield label_name[len(f'{prefix}: '):]


def get_label(pr, prefix):
    for label in get_labels(pr, prefix):
        return label


def get_previous_final(repo, current_release):
    assert current_release.rc is not None, "Need an rc to find the previous final release."
    previous = None
    for release in repo.releases(current_release.rc + 1):
        previous = release
    return previous


class Version:

    def __init__(self, major=0, minor=0, micro=0, rc=None):
        self.major = int(major)
        self.minor = int(minor)
        self.micro = int(micro)
        self.rc = rc if rc is None else int(rc)

    @classmethod
    def from_string(cls, version_string):
        (major, minor, micro), rc = version_string.split('.'), None
        if 'rc' in micro:
            micro, rc = micro.split('rc')
        return cls(major, minor, micro, rc)

    @classmethod
    def from_content(cls, content):
        src = content.decoded.decode('utf-8')
        version = re.search('__version__ = "(.*?)"', src).group(1)
        return cls.from_string(version)

    def increment(self, action):
        cls = self.__class__

        if action == '*-rc':
            assert self.rc is not None, f"Can't drop rc designation because {self} is already not an rc."
            return cls(self.major, self.minor, self.micro)
        elif action == '*+rc':
            assert self.rc is not None, "Must already be an rc to increment."
            return cls(self.major, self.minor, self.micro, self.rc+1)

        assert self.rc is None, f"Can't start a new rc because {self} is already an rc."
        if action == 'major+rc':
            return cls(self.major+1, rc=1)
        elif action == 'minor+rc':
            return cls(self.major, self.minor+1, rc=1)
        elif action == 'micro+rc':
            return cls(self.major, self.minor, self.micro+1, 1)

        raise ValueError(f'unknown action: {action}')

    @property
    def tag(self):
        return f'v{self}'

    def __str__(self):
        version = '.'.join(str(p) for p in [self.major, self.minor, self.micro])
        if self.rc is not None:
            version += f'rc{self.rc}'
        return version


def release(args):
    gh = get_github()
    repo = gh.repository('lbryio', 'lbry')
    version_file = repo.file_contents('lbrynet/__init__.py')

    current_version = Version.from_content(version_file)
    print(f'Current Version: {current_version}')
    new_version = current_version.increment(args.action)
    print(f'    New Version: {new_version}')
    print()

    if args.action == '*-rc':
        previous_release = get_previous_final(repo, current_version)
    else:
        previous_release = repo.release_from_tag(current_version.tag)

    areas = {}
    for pr in gh.search_issues(f"merged:>={previous_release._json_data['created_at']} repo:lbryio/lbry"):
        for area_name in get_labels(pr, 'area'):
            area = areas.setdefault(area_name, [])
            type_label = get_label(pr, "type")
            if not (args.action == '*-rc' and type_label == 'fixup'):
                area.append(f'  * [{type_label}] {pr.title} ({pr.html_url}) by {pr.user["login"]}')

    area_names = list(areas.keys())
    area_names.sort()

    body = io.StringIO()
    w = lambda s: body.write(s+'\n')

    w(f'## [{new_version}] - {date.today().isoformat()}')
    for area in area_names:
        prs = areas[area]
        area = AREA_RENAME.get(area, area.capitalize())
        w('')
        w(f'### {area}')
        for pr in prs:
            w(pr)

    print(body.getvalue())

    if not args.dry_run:

        commit = version_file.update(
          new_version.tag,
          version_file.decoded.decode('utf-8').replace(str(current_version), str(new_version)).encode()
        )['commit']

        repo.create_tag(
            tag=new_version.tag,
            message=new_version.tag,
            sha=commit.sha,
            obj_type='commit',
            tagger=commit.committer
        )

        repo.create_release(
            new_version.tag,
            name=new_version.tag,
            body=body.getvalue(),
            draft=True,
            prerelease=new_version.rc is not None
        )


class TestReleaseTool(unittest.TestCase):

    def test_version_parsing(self):
        self.assertTrue(str(Version.from_string('1.2.3')), '1.2.3')
        self.assertTrue(str(Version.from_string('1.2.3rc4')), '1.2.3rc4')

    def test_version_increment(self):
        v = Version.from_string('1.2.3')
        self.assertTrue(str(v.increment('major+rc')), '2.0.0rc1')
        self.assertTrue(str(v.increment('minor+rc')), '1.3.0rc1')
        self.assertTrue(str(v.increment('micro+rc')), '1.2.4rc1')
        with self.assertRaisesRegex(AssertionError, "Must already be an rc to increment."):
            v.increment('*+rc')
        with self.assertRaisesRegex(AssertionError, "Can't drop rc designation"):
            v.increment('*-rc')

        v = Version.from_string('1.2.3rc3')
        self.assertTrue(str(v.increment('*+rc')), '1.2.3rc4')
        self.assertTrue(str(v.increment('*-rc')), '1.2.3')
        with self.assertRaisesRegex(AssertionError, "already an rc"):
            v.increment('major+rc')
        with self.assertRaisesRegex(AssertionError, "already an rc"):
            v.increment('minor+rc')
        with self.assertRaisesRegex(AssertionError, "already an rc"):
            v.increment('micro+rc')


def test():
    runner = unittest.TextTestRunner(verbosity=2)
    loader = unittest.TestLoader()
    suite = loader.loadTestsFromTestCase(TestReleaseTool)
    runner.run(suite)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--test", default=False, action="store_true", help="run unit tests")
    parser.add_argument("--dry-run", default=False, action="store_true", help="show what will be done")
    parser.add_argument("action", nargs="?", choices=['major+rc', 'minor+rc', 'micro+rc', '*+rc', '*-rc'])
    args = parser.parse_args()
    if args.test:
        test()
    else:
        release(args)


if __name__ == "__main__":
    main()
