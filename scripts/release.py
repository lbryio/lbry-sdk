import os
import re
import io
import sys
import json
import argparse
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


class Version:

    def __init__(self, major=0, minor=0, micro=0, rc=None):
        self.major = int(major)
        self.minor = int(minor)
        self.micro = int(micro)
        self.rc = rc

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

    def increment(self, part):
        cls = self.__class__
        if part == 'major':
            return cls(self.major+1)
        elif part == 'minor':
            return cls(self.major, self.minor+1)
        elif part == 'micro':
            return cls(self.major, self.minor, self.micro+1)
        elif part == 'rc':
            if self.rc is None:
                return cls(self.major, self.minor, self.micro+1, 1)
            else:
                return cls(self.major, self.minor, self.micro, self.rc+1)
        else:
            raise ValueError(f'unknown version part: {part}')

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
    new_version = current_version.increment(args.increment)
    print(f'    New Version: {new_version}')

    current_release = repo.release_from_tag(current_version.tag)

    areas = {}
    for pr in gh.search_issues(f"merged:>={current_release._json_data['created_at']} repo:lbryio/lbry"):
        for area_name in get_labels(pr, 'area'):
            area = areas.setdefault(area_name, [])
            area.append(f'  * [{get_label(pr, "type")}] {pr.title} ({pr.html_url})')

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
        prerelease=True
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("increment", choices=['major', 'minor', 'micro', 'rc'])
    release(parser.parse_args())


if __name__ == "__main__":
    main()
