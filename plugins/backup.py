
from yap import YapPlugin, YapError
import os

class BackupPlugin(YapPlugin):
    def __init__(self, yap):
        self.yap = yap

    def pre_revert(self, *args, **flags):
        files = set(args)
        changed = set(self.yap._get_staged_files() + self.yap._get_unstaged_files())
        if '-a' in flags:
            x = changed
        else:
            x = files.intersection(changed)

        for f in x:
            os.system("cp %s %s~" % (f, f))
