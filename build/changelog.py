import datetime
import re

CHANGELOG_START_RE = re.compile(r'^\#\# \[Unreleased\]')
CHANGELOG_END_RE = re.compile(r'^\#\# \[.*\] - \d{4}-\d{2}-\d{2}')
# if we come across a section header between two release section headers
# then we probably have an improperly formatted changelog
CHANGELOG_ERROR_RE = re.compile(r'^\#\# ')
SECTION_RE = re.compile(r'^\#\#\# (.*)$')
EMPTY_RE = re.compile(r'^\w*\*\w*$')
ENTRY_RE = re.compile(r'\* (.*)')
VALID_SECTIONS = ['Added', 'Changed', 'Deprecated', 'Removed', 'Fixed', 'Security']

# allocate some entries to cut-down on merge conflicts
TEMPLATE = """### Added
  *
  *

### Changed
  *
  *

### Fixed
  *
  *

"""


class Changelog(object):
    def __init__(self, path):
        self.path = path
        self.start = []
        self.unreleased = []
        self.rest = []
        self._parse()

    def _parse(self):
        with open(self.path) as fp:
            lines = fp.readlines()

        unreleased_start_found = False
        unreleased_end_found = False

        for line in lines:
            if not unreleased_start_found:
                self.start.append(line)
                if CHANGELOG_START_RE.search(line):
                    unreleased_start_found = True
                continue
            if unreleased_end_found:
                self.rest.append(line)
                continue
            if CHANGELOG_END_RE.search(line):
                self.rest.append(line)
                unreleased_end_found = True
                continue
            if CHANGELOG_ERROR_RE.search(line):
                raise Exception(
                    'Failed to parse {}: {}'.format(self.path, 'unexpected section header found'))
            self.unreleased.append(line)

        self.unreleased = self._normalize_section(self.unreleased)

    @staticmethod
    def _normalize_section(lines):
        """Parse a changelog entry and output a normalized form"""
        sections = {}
        current_section_name = None
        current_section_contents = []
        for line in lines:
            line = line.strip()
            if not line or EMPTY_RE.match(line):
                continue
            match = SECTION_RE.match(line)
            if match:
                if current_section_contents:
                    sections[current_section_name] = current_section_contents
                current_section_contents = []
                current_section_name = match.group(1)
                if current_section_name not in VALID_SECTIONS:
                    raise ValueError("Section '{}' is not valid".format(current_section_name))
                continue
            match = ENTRY_RE.match(line)
            if match:
                current_section_contents.append(match.group(1))
                continue
            raise Exception('Something is wrong with line: {}'.format(line))
        if current_section_contents:
            sections[current_section_name] = current_section_contents

        output = []
        for section in VALID_SECTIONS:
            if section not in sections:
                continue
            output.append('### {}'.format(section))
            for entry in sections[section]:
                output.append(' * {}'.format(entry))
        return output

    def get_unreleased(self):
        return '\n'.join(self.unreleased) if self.unreleased else None

    def bump(self, version):
        if not self.unreleased:
            return

        today = datetime.datetime.today()
        header = '## [{}] - {}\n'.format(version, today.strftime('%Y-%m-%d'))

        changelog_data = (
            ''.join(self.start) +
            TEMPLATE +
            header +
            '\n'.join(self.unreleased) + '\n\n'
            + ''.join(self.rest)
        )

        with open(self.path, 'w') as fp:
            fp.write(changelog_data)
