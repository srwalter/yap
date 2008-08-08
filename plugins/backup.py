
from yap.yap import YapCore, YapError
import os

class BackupPlugin(YapCore):
    "Save a backup of files before reverting them"

    def cmd_revert(self, *args, **flags):
        files = set(args)
        changed = set(self._get_staged_files() + self._get_unstaged_files())

        if '-a' in flags:
            x = changed
        else:
            x = files.intersection(changed)

        for f in x:
            os.system("cp %s %s~" % (f, f))
	super(BackupPlugin, self).cmd_revert(*args, **flags)
