import os
import re
import io
import sys
import yaml
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
    'api': 'API',
    'dht': 'DHT'
}


def get_github():
    config_path = os.path.expanduser('~/.config/gh/hosts.yml')
    if os.path.exists(config_path):
        with open(config_path, 'r') as config_file:
            config = yaml.load(config_file, Loader=yaml.FullLoader)
            return github3.login(token=config['github.com']['oauth_token'])

    print('To run release tool you need to first login using the github cli:')
    print('')
    print('  $ gh auth login')
    print('')
    sys.exit(1)


def get_labels(pr, prefix):
    for label in pr.labels:
        label_name = label['name']
        if label_name.startswith(f'{prefix}: '):
            yield label_name[len(f'{prefix}: '):]


def get_label(pr, prefix):
    for label in get_labels(pr, prefix):
        return label


BACKWARDS_INCOMPATIBLE = 'backwards-incompatible:'
RELEASE_TEXT = 'release-text:'
RELEASE_TEXT_LINES = 'release-text-lines:'


def get_backwards_incompatible(desc: str):
    for line in desc.splitlines():
        if line.startswith(BACKWARDS_INCOMPATIBLE):
            yield line[len(BACKWARDS_INCOMPATIBLE):]


def get_release_text(desc: str):
    in_release_lines = False
    for line in desc.splitlines():
        if in_release_lines:
            yield line.rstrip()
        elif line.startswith(RELEASE_TEXT_LINES):
            in_release_lines = True
        elif line.startswith(RELEASE_TEXT):
            yield line[len(RELEASE_TEXT):].strip()
            yield ''


class Version:

    def __init__(self, major=0, minor=0, micro=0):
        self.major = int(major)
        self.minor = int(minor)
        self.micro = int(micro)

    @classmethod
    def from_string(cls, version_string):
        (major, minor, micro), rc = version_string.split('.'), None
        if 'rc' in micro:
            micro, rc = micro.split('rc')
        return cls(major, minor, micro)

    @classmethod
    def from_content(cls, content):
        src = content.decoded.decode('utf-8')
        version = re.search('__version__ = "(.*?)"', src).group(1)
        return cls.from_string(version)

    def increment(self, action):
        cls = self.__class__

        if action == 'major':
            return cls(self.major+1)
        elif action == 'minor':
            return cls(self.major, self.minor+1)
        elif action == 'micro':
            return cls(self.major, self.minor, self.micro+1)

        raise ValueError(f'unknown action: {action}')

    @property
    def tag(self):
        return f'v{self}'

    def __str__(self):
        return '.'.join(str(p) for p in [self.major, self.minor, self.micro])


def release(args):
    gh = get_github()
    repo = gh.repository('lbryio', 'lbry-sdk')
    version_file = repo.file_contents('lbry/__init__.py')

    if not args.confirm:
        print("\nDRY RUN ONLY. RUN WITH --confirm TO DO A REAL RELEASE.\n")

    current_version = Version.from_content(version_file)
    print(f'Current Version: {current_version}')

    if args.action == 'current':
        new_version = current_version
    else:
        new_version = current_version.increment(args.action)
    print(f'    New Version: {new_version}')

    previous_release = repo.release_from_tag(args.start_tag or current_version.tag)

    print(f' Changelog From: {previous_release.tag_name} ({previous_release.created_at})')
    print()

    incompats = []
    release_texts = []
    unlabeled = []
    fixups = []
    areas = {}
    for pr in gh.search_issues(f"merged:>={previous_release._json_data['created_at']} repo:lbryio/lbry-sdk"):
        area_labels = list(get_labels(pr, 'area'))
        type_label = get_label(pr, 'type')
        pr_url = f'[#{pr.number}]({pr.html_url})'
        user_url = f'[{pr.user["login"]}]({pr.user["html_url"]})'
        if area_labels and type_label:
            for area_name in area_labels:
                for incompat in get_backwards_incompatible(pr.body or ""):
                    incompats.append(f'  * [{area_name}] {incompat.strip()} ({pr_url})')
                for release_text in get_release_text(pr.body or ""):
                    release_texts.append(release_text)
                if type_label == 'fixup':
                    fixups.append(f'  * {pr.title} ({pr_url}) by {user_url}')
                else:
                    area = areas.setdefault(area_name, [])
                    area.append(f'  * [{type_label}] {pr.title} ({pr_url}) by {user_url}')
        else:
            unlabeled.append(f'  * {pr.title} ({pr_url}) by {user_url}')

    area_names = list(areas.keys())
    area_names.sort()

    body = io.StringIO()
    w = lambda s: body.write(s+'\n')

    w(f'## [{new_version}] - {date.today().isoformat()}')
    if release_texts:
        w('')
        for release_text in release_texts:
            w(release_text)
    if incompats:
        w('')
        w(f'### Backwards Incompatible Changes')
        for incompat in incompats:
            w(incompat)
    for area in area_names:
        prs = areas[area]
        area = AREA_RENAME.get(area.lower(), area.capitalize())
        w('')
        w(f'### {area}')
        for pr in prs:
            w(pr)

    print(body.getvalue())

    if unlabeled:
        print('The following PRs were skipped and not included in changelog:')
        for skipped in unlabeled:
            print(skipped)

    if fixups:
        print('The following PRs were marked as fixups and not included in changelog:')
        for skipped in fixups:
            print(skipped)

    if args.confirm:

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
        )

    return 0


class TestReleaseTool(unittest.TestCase):

    def test_version_parsing(self):
        self.assertTrue(str(Version.from_string('1.2.3')), '1.2.3')
        self.assertTrue(str(Version.from_string('1.2.3rc4')), '1.2.3rc4')

    def test_version_increment(self):
        v = Version.from_string('1.2.3')
        self.assertTrue(str(v.increment('major')), '2.0.0')
        self.assertTrue(str(v.increment('minor')), '1.3.0')
        self.assertTrue(str(v.increment('micro')), '1.2.4')


def test():
    runner = unittest.TextTestRunner(verbosity=2)
    loader = unittest.TestLoader()
    suite = loader.loadTestsFromTestCase(TestReleaseTool)
    return 0 if runner.run(suite).wasSuccessful() else 1


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--confirm", default=False, action="store_true",
                        help="without this flag, it will only print what it will do but will not actually do it")
    parser.add_argument("--start-tag", help="custom starting tag for changelog generation")
    parser.add_argument("action", choices=['test', 'current', 'major', 'minor', 'micro'])
    args = parser.parse_args()

    if args.action == "test":
        code = test()
    else:
        code = release(args)

    print()
    return code


if __name__ == "__main__":
    sys.exit(main())
