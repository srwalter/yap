
from yap import YapPlugin
from yap.util import get_output, takes_options
import pickle
import os

class TCommitPlugin(YapPlugin):
    def __init__(self, yap):
        self.yap = yap

    def _add_branch(self, branch):
        repo = get_output("git rev-parse --git-dir")
        if not repo:
            return
        dir = os.path.join(repo[0], 'yap')
	try:
	    os.mkdir(dir)
	except IOError:
	    pass
        state_file = os.path.join(dir, 'tcommit')

        b = self._get_branches()
        b.add(branch)
        pickle.dump(b, file(state_file, 'w'))

    def _get_branches(self):
        repo = get_output("git rev-parse --git-dir")
        state_file = os.path.join(repo[0], 'yap', 'tcommit')

        try:
            b = pickle.load(file(state_file))
        except IOError:
            b = set()
        return b

    def _remove_branch(self, branch):
        repo = get_output("git rev-parse --git-dir")
        if not repo:
            return
        state_file = os.path.join(repo[0], 'yap', 'tcommit')

        b = self._get_branches()
        b.remove(branch)
        pickle.dump(b, file(state_file, 'w'))

    @takes_options("t")
    def cmd_commit(self, *args, **flags):
        if '-t' in flags:
            self.yap.cmd_commit(*[], **{'-a': 1, '-m': 'yap wip'})
            branch = get_output("git symbolic-ref HEAD")
            if branch:
                self._add_branch(branch[0])
        else:
            self.yap._call_base("cmd_commit", *args, **flags)

    def post_switch(self):
        branch = get_output("git symbolic-ref HEAD")
        if branch[0] in self._get_branches():
            self.yap.cmd_uncommit()
            self._remove_branch(branch[0])
