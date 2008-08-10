
from yap.yap import YapCore
from yap.util import get_output, takes_options
import pickle
import os

class TCommitPlugin(YapCore):
    "Provide a 'temporory commit' mechanism"

    def _add_branch(self, branch):
        repo = get_output("git rev-parse --git-dir")
        if not repo:
            return
        dir = os.path.join(repo[0], 'yap')
	try:
	    os.mkdir(dir)
	except OSError:
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
	    override = True
	    args = []
	    flags = {'-a': 1, '-m': 'yap wip'}
	else:
	    override = False

	super(TCommitPlugin, self).cmd_commit(*args, **flags)

	if override is True:
            branch = get_output("git symbolic-ref HEAD")
            if branch:
                self._add_branch(branch[0])

    def cmd_branch(self, *args, **flags):
        if '-d' in flags:
            if args:
                branch = args[0]
                self._remove_branch(branch)
        
        super(TCommitPlugin, self).cmd_commit(*args, **flags)

    def cmd_switch(self, *args, **flags):
	super(TCommitPlugin, self).cmd_switch(*args, **flags)

        branch = get_output("git symbolic-ref HEAD")
        if branch[0] in self._get_branches():
            self.cmd_uncommit()
            self._remove_branch(branch[0])
