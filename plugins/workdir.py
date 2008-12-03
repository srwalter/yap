
from yap.yap import YapCore, YapError
from yap.util import get_output, takes_options, run_safely

import os
import tempfile

class WorkdirPlugin(YapCore):
    "Create extra work directories of a repository"

    def __init__(self, *args, **flags):
	super(WorkdirPlugin, self).__init__(*args, **flags)

    def _lock_branch(self, branch, locked_by):
        repo = get_output('git rev-parse --git-dir')[0]
        dir = os.path.join(repo, 'yap', 'lock')
        try:
            os.mkdir(dir)
        except OSError:
            pass

        fd, tmplock = tempfile.mkstemp("yap")
        os.write(fd, locked_by)
        os.close(fd)
        while True:
            lockfile = os.path.join(dir, branch.replace('/', '\/'))
            try:
                os.link(tmplock, lockfile)
                break
            except OSError:
                fd = file(lockfile)
                user = fd.readline()
                # If the workdir has been deleted, break his lock
                if os.access(user, os.R_OK):
                    raise YapError("That branch is being used by an existing workdir")
                os.unlink(lockfile)
                continue

    def cmd_workdir(self, branch, workdir=None):
        self._check_git()

        branches = get_output("git for-each-ref --format='%(refname)' 'refs/heads'")
        if 'refs/heads/%s' % branch not in branches:
            raise YapError("Not a branch: %s" % branch)

        current = get_output("git symbolic-ref HEAD")[0]

        repo = get_output('git rev-parse --git-dir')[0]
        repo = os.path.join(os.getcwd(), repo)
        repodir = os.path.dirname(repo)
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
                  "hooks", "packed-refs", "remotes", "svn"]:
            if os.path.dirname(x):
                os.makedirs(os.path.dirname(x))
            os.symlink(os.path.join(repo, x), x)

        run_safely("cp %s HEAD" % os.path.join(repo, 'HEAD'))
        os.chdir("..")
        run_safely("git symbolic-ref HEAD refs/heads/%s" % branch)
        self.cmd_revert(**{'-a': 1})

    def cmd_switch(self, branch, *args, **flags):
        self._check_git()

        repo = get_output('git rev-parse --git-dir')[0]
        self._lock_branch(branch, repo)
        super(WorkdirPlugin, self).cmd_switch(branch, *args, **flags)
