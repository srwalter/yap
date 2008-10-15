
from yap.yap import YapCore, YapError
from yap.util import run_command
import os

class BackupPlugin(YapCore):
    "Save a backup of files before reverting them"

    def cmd_revert(self, *args, **flags):
        files = set(args)
        changed = set(self._get_staged_files() + self._get_unstaged_files())

        if '-a' in flags:
            files = changed
        else:
            files = files.intersection(changed)

	files = [ x for x in files if os.access(x, os.R_OK) ]

        for f in files:
	    run_command("cp %s %s~" % (f, f))
	super(BackupPlugin, self).cmd_revert(*args, **flags)
