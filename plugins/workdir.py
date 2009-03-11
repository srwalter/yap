
from yap.yap import YapCore, YapError
from yap.util import get_output, takes_options, run_safely

import os
import tempfile

class WorkdirPlugin(YapCore):
    "Create extra work directories of a repository"

    def __init__(self, *args, **flags):
	super(WorkdirPlugin, self).__init__(*args, **flags)

    def _unlock_branch(self, branch):
        repo = get_output('git rev-parse --git-dir')[0]
        dir = os.path.join(repo, 'yap', 'lock')
        try:
            os.mkdir(dir)
        except OSError:
            pass

        lockfile = os.path.join(dir, branch.replace('/', '\/'))

        try:
            os.unlink(lockfile)
        except OSError:
            pass

    def _lock_branch(self, branch, locked_by):
        repo = get_output('git rev-parse --git-dir')[0]
        dir = os.path.join(repo, 'yap', 'lock')
        try:
            os.mkdir(dir)
        except OSError:
            pass

        fd, tmplock = tempfile.mkstemp("yap", dir=dir)
	try:
	    os.write(fd, locked_by)
	    os.close(fd)
	    while True:
		lockfile = os.path.join(dir, branch.replace('/', '\/'))
		try:
		    os.link(tmplock, lockfile)
		    break
		except OSError, e:
		    try:
			fd = file(lockfile)
		    except:
			raise e
		    user = fd.readline()
		    # If the workdir has been deleted, break his lock
		    if os.access(user, os.R_OK):
			raise YapError("That branch is being used by an existing workdir")
		    os.unlink(lockfile)
		    continue
	finally:
	    os.unlink(tmplock)

    def _get_repodir(self):
        repo = get_output('git rev-parse --git-dir')[0]
	if not repo.startswith('/'):
	    repo = os.path.join(os.getcwd(), repo)
        repodir = os.path.dirname(repo)
	return repodir

    def cmd_workdir(self, branch, workdir=None):
        "<branch> [workdir]"

        self._check_git()

        branches = get_output("git for-each-ref --format='%(refname)' 'refs/heads'")
        if 'refs/heads/%s' % branch not in branches:
            raise YapError("Not a branch: %s" % branch)

        current = get_output("git symbolic-ref HEAD")[0]
	repodir = self._get_repodir()
	repo = os.path.join(repodir, '.git')
        if workdir is None:
            repoparent, reponame = os.path.split(repodir)
            workdir = os.path.join(repoparent, "%s-%s" % (reponame, branch))

        # Make sure the current branch is locked
        try:
            self._lock_branch(current.replace('refs/heads/', ''), repodir)
        except:
            pass

        self._lock_branch(branch, workdir)

        try:
            os.mkdir(workdir)
        except OSError, e:
            raise YapError("Can't create new workdir: %s (%s)" % (workdir, e))

        os.chdir(workdir)
        os.mkdir(".git")
        os.chdir(".git")

        for x in ["config", "refs", "logs/refs", "objects", "info",
                  "hooks", "packed-refs", "remotes", "yap", "svn"]:
            if os.path.dirname(x):
                os.makedirs(os.path.dirname(x))
            os.symlink(os.path.join(repo, x), x)

        run_safely("cp %s HEAD" % os.path.join(repo, 'HEAD'))
        os.chdir("..")
        run_safely("git symbolic-ref HEAD refs/heads/%s" % branch)
        self.cmd_revert(**{'-a': 1})

        print "Workdir created at %s for branch %s" % (workdir, branch)

    def cmd_branch(self, *args, **flags):
	if '-d' in flags:
	    branch = flags['-d']
	    repodir = self._get_repodir()
	    self._lock_branch(branch, repodir)
	else:
	    branch = None

	try:
	    super(WorkdirPlugin, self).cmd_branch(*args, **flags)
	finally:
	    if branch:
		self._unlock_branch(branch)

    def cmd_switch(self, branch, *args, **flags):
        self._check_git()

        current = get_output("git symbolic-ref HEAD")[0]

	repodir = self._get_repodir()
        self._lock_branch(branch, repodir)

        try:
            super(WorkdirPlugin, self).cmd_switch(branch, *args, **flags)
        except:
            self._unlock_branch(branch)
            raise

        self._unlock_branch(current.replace('refs/heads/', ''))
