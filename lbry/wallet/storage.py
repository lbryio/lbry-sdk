import os
import stat
import json
import asyncio


class WalletStorage:
    VERSION = 1

    def __init__(self, path=None):
        self.path = path

    def sync_read(self):
        with open(self.path, 'r') as f:
            json_data = f.read()
            json_dict = json.loads(json_data)
            if json_dict.get('version') == self.VERSION:
                return json_dict
            else:
                return self.upgrade(json_dict)

    async def read(self):
        return await asyncio.get_running_loop().run_in_executor(
            None, self.sync_read
        )

    def upgrade(self, json_dict):
        version = json_dict.pop('version', -1)
        if version == -1:
            pass
        json_dict['version'] = self.VERSION
        return json_dict

    def sync_write(self, json_dict):

        json_data = json.dumps(json_dict, indent=4, sort_keys=True)
        if self.path is None:
            return json_data

        temp_path = "{}.tmp.{}".format(self.path, os.getpid())
        with open(temp_path, "w") as f:
            f.write(json_data)
            f.flush()
            os.fsync(f.fileno())

        if os.path.exists(self.path):
            mode = os.stat(self.path).st_mode
        else:
            mode = stat.S_IREAD | stat.S_IWRITE
        try:
            os.rename(temp_path, self.path)
        except Exception:  # pylint: disable=broad-except
            os.remove(self.path)
            os.rename(temp_path, self.path)
        os.chmod(self.path, mode)

    async def write(self, json_dict):
        return await asyncio.get_running_loop().run_in_executor(
            None, self.sync_write, json_dict
        )
