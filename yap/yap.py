import sys
import os
import glob
import getopt
import pickle
import tempfile

from plugin import YapPlugin
from util import *

class ShellError(Exception):
    def __init__(self, cmd, rc):
	self.cmd = cmd
	self.rc = rc

    def __str__(self):
	return "%s returned %d" % (self.cmd, self.rc)

class YapError(Exception):
    def __init__(self, msg):
        self.msg = msg

    def __str__(self):
        return self.msg

class Yap(object):
    def __init__(self):
        self.plugins = set()
        self.overrides = []
        plugindir = os.path.expanduser("~/.yap/plugins")
        for p in glob.glob(os.path.join(plugindir, "*.py")):
            glbls = {}
            execfile(p, glbls)
            for cls in glbls.values():
                if not type(cls) == type:
                    continue
                if not issubclass(cls, YapPlugin):
                    continue
                if cls is YapPlugin:
                    continue
                x = cls(self)
                self.plugins.add(x)

                for func in dir(x):
                    if not func.startswith('cmd_'):
                        continue
                    if func in self.overrides:
                        print >>sys.stderr, "Plugin %s overrides already overridden function %s.  Disabling" % (p, func)
                        self.plugins.remove(x)
                        break

    def _add_new_file(self, file):
        repo = get_output('git rev-parse --git-dir')[0]
        dir = os.path.join(repo, 'yap')
        try:
            os.mkdir(dir)
        except OSError:
            pass
        files = self._get_new_files()
        files.append(file)
        path = os.path.join(dir, 'new-files')
        pickle.dump(files, open(path, 'w'))

    def _get_new_files(self):
        repo = get_output('git rev-parse --git-dir')[0]
        path = os.path.join(repo, 'yap', 'new-files')
        try:
            files = pickle.load(file(path))
        except IOError:
            files = []

        x = []
        for f in files:
            # if f in the index
            if get_output("git ls-files --cached '%s'" % f) != []:
                continue
            x.append(f)
        return x

    def _remove_new_file(self, file):
        files = self._get_new_files()
        files = filter(lambda x: x != file, files)

        repo = get_output('git rev-parse --git-dir')[0]
        path = os.path.join(repo, 'yap', 'new-files')
        pickle.dump(files, open(path, 'w'))

    def _clear_new_files(self):
        repo = get_output('git rev-parse --git-dir')[0]
        path = os.path.join(repo, 'yap', 'new-files')
        os.unlink(path)

    def _assert_file_exists(self, file):
        if not os.access(file, os.R_OK):
            raise YapError("No such file: %s" % file)

    def _get_staged_files(self):
        if run_command("git rev-parse HEAD"):
            files = get_output("git ls-files --cached")
        else:
            files = get_output("git diff-index --cached --name-only HEAD")
	unmerged = self._get_unmerged_files()
	if unmerged:
	    unmerged = set(unmerged)
	    files = set(files).difference(unmerged)
	    files = list(files)
        return files

    def _get_unstaged_files(self):
        files = get_output("git ls-files -m")
        prefix = get_output("git rev-parse --show-prefix")
	if prefix:
	    files = [ os.path.join(prefix[0], x) for x in files ]
        files += self._get_new_files()
	unmerged = self._get_unmerged_files()
	if unmerged:
	    unmerged = set(unmerged)
	    files = set(files).difference(unmerged)
	    files = list(files)
        return files

    def _get_unmerged_files(self):
	files = get_output("git ls-files -u")
	files = [ x.replace('\t', ' ').split(' ')[3] for x in files ]
        prefix = get_output("git rev-parse --show-prefix")
	if prefix:
	    files = [ os.path.join(prefix[0], x) for x in files ]
	return list(set(files))

    def _delete_branch(self, branch, force):
        current = get_output("git symbolic-ref HEAD")[0]
        current = current.replace('refs/heads/', '')
        if branch == current:
            raise YapError("Can't delete current branch")

        ref = get_output("git rev-parse --verify 'refs/heads/%s'" % branch)
        if not ref:
            raise YapError("No such branch: %s" % branch)
        run_safely("git update-ref -d 'refs/heads/%s' '%s'" % (branch, ref[0]))

        if not force:
            name = get_output("git name-rev --name-only '%s'" % ref[0])[0]
            if name == 'undefined':
                run_command("git update-ref 'refs/heads/%s' '%s'" % (branch, ref[0]))
                raise YapError("Refusing to delete leaf branch (use -f to force)")
    def _get_pager_cmd(self):
        if 'YAP_PAGER' in os.environ:
            return os.environ['YAP_PAGER']
        elif 'GIT_PAGER' in os.environ:
            return os.environ['GIT_PAGER']
        elif 'PAGER' in os.environ:
            return os.environ['PAGER']
        else:
            return "more"

    def _add_one(self, file):
        self._assert_file_exists(file)
        x = get_output("git ls-files '%s'" % file)
        if x != []:
            raise YapError("File '%s' already in repository" % file)
        self._add_new_file(file)

    def _rm_one(self, file):
        self._assert_file_exists(file)
        if get_output("git ls-files '%s'" % file) != []:
            run_safely("git rm --cached '%s'" % file)
        self._remove_new_file(file)

    def _stage_one(self, file):
        self._assert_file_exists(file)
        run_safely("git update-index --add '%s'" % file)

    def _unstage_one(self, file):
        self._assert_file_exists(file)
        if run_command("git rev-parse HEAD"):
            run_safely("git update-index --force-remove '%s'" % file)
        else:
            run_safely("git diff-index -p HEAD '%s' | git apply -R --cached" % file)

    def _revert_one(self, file):
        self._assert_file_exists(file)
        self._unstage_one(file)
        run_safely("git checkout-index -u -f '%s'" % file)

    def _parse_commit(self, commit):
        lines = get_output("git cat-file commit '%s'" % commit)
        commit = {}

        mode = None
        for l in lines:
            if mode != 'commit' and l.strip() == "":
                mode = 'commit'
                commit['log'] = []
                continue
            if mode == 'commit':
                commit['log'].append(l)
                continue

            x = l.split(' ')
            k = x[0]
            v = ' '.join(x[1:])
            commit[k] = v
        commit['log'] = '\n'.join(commit['log'])
        return commit

    def _check_commit(self, **flags):
        if '-a' in flags and '-d' in flags:
            raise YapError("Conflicting flags: -a and -d")

        if '-d' not in flags and self._get_unstaged_files():
            if '-a' not in flags and self._get_staged_files():
                raise YapError("Staged and unstaged changes present.  Specify what to commit")
            os.system("git diff-files -p | git apply --cached")
            for f in self._get_new_files():
                self._stage_one(f)

    def _do_uncommit(self):
        commit = self._parse_commit("HEAD")
        repo = get_output('git rev-parse --git-dir')[0]
        dir = os.path.join(repo, 'yap')
        try:
            os.mkdir(dir)
        except OSError:
            pass
        msg_file = os.path.join(dir, 'msg')
        fd = file(msg_file, 'w')
        print >>fd, commit['log']
        fd.close()

        tree = get_output("git rev-parse --verify HEAD^")
        run_safely("git update-ref -m uncommit HEAD '%s'" % tree[0])

    def _do_commit(self, msg=None):
        tree = get_output("git write-tree")[0]
        parent = get_output("git rev-parse --verify HEAD 2> /dev/null")[0]

        if os.environ.has_key('YAP_EDITOR'):
            editor = os.environ['YAP_EDITOR']
        elif os.environ.has_key('GIT_EDITOR'):
            editor = os.environ['GIT_EDITOR']
        elif os.environ.has_key('EDITOR'):
            editor = os.environ['EDITOR']
        else:
            editor = "vi"

        fd, tmpfile = tempfile.mkstemp("yap")
        os.close(fd)


	if msg is None:
	    repo = get_output('git rev-parse --git-dir')[0]
	    msg_file = os.path.join(repo, 'yap', 'msg')
	    if os.access(msg_file, os.R_OK):
		fd1 = file(msg_file)
		fd2 = file(tmpfile, 'w')
		for l in fd1.xreadlines():
		    print >>fd2, l.strip()
		fd2.close()
		os.unlink(msg_file)
	    if os.system("%s '%s'" % (editor, tmpfile)) != 0:
		raise YapError("Editing commit message failed")
	    fd = file(tmpfile)
	    msg = fd.readlines()
	    msg = ''.join(msg)
	
	msg = msg.strip()
	if not msg:
	    raise YapError("Refusing to use empty commit message")

	(fd_w, fd_r) = os.popen2("git stripspace > %s" % tmpfile)
	print >>fd_w, msg,
	fd_w.close()
	fd_r.close()

        if parent != 'HEAD':
            commit = get_output("git commit-tree '%s' -p '%s' < '%s'" % (tree, parent, tmpfile))
        else:
            commit = get_output("git commit-tree '%s' < '%s'" % (tree, tmpfile))

        os.unlink(tmpfile)
        run_safely("git update-ref HEAD '%s'" % commit[0])

    def _check_rebasing(self):
        repo = get_output('git rev-parse --git-dir')[0]
        dotest = os.path.join(repo, '.dotest')
        if os.access(dotest, os.R_OK):
            raise YapError("A git operation is in progress.  Complete it first")
        dotest = os.path.join(repo, '..', '.dotest')
        if os.access(dotest, os.R_OK):
            raise YapError("A git operation is in progress.  Complete it first")

    def _list_remotes(self):
        remotes = get_output("git config --get-regexp '^remote.*.url'")
        for x in remotes:
            remote, url = x.split(' ')
            remote = remote.replace('remote.', '')
            remote = remote.replace('.url', '')
            yield remote, url

    def _unstage_all(self):
	try:
	    run_safely("git read-tree -m HEAD")
	except ShellError:
	    run_safely("git read-tree HEAD")
	    run_safely("git update-index -q --refresh")

    def _get_tracking(self, current):
	remote = get_output("git config branch.%s.remote" % current)
        if not remote:
            raise YapError("No tracking branch configured for '%s'" % current)

        merge = get_output("git config branch.%s.merge" % current)
        if not merge:
            raise YapError("No tracking branch configured for '%s'" % current)
        return remote[0], merge

    @short_help("make a local copy of an existing repository")
    @long_help("""
The first argument is a URL to the existing repository.  This can be an
absolute path if the repository is local, or a URL with the git://,
ssh://, or http:// schemes.  By default, the directory used is the last
component of the URL, sans '.git'.  This can be overridden by providing
a second argument.
""")
    def cmd_clone(self, url, directory=None):
        "<url> [directory]"

        if '://' not in url and url[0] != '/':
            url = os.path.join(os.getcwd(), url)

        url = url.rstrip('/')
        if directory is None:
            directory = url.rsplit('/')[-1]
            directory = directory.replace('.git', '')

        try:
            os.mkdir(directory)
        except OSError:
            raise YapError("Directory exists: %s" % directory)
        os.chdir(directory)
        self.cmd_init()
        self.cmd_repo("origin", url)
        self.cmd_fetch("origin")

        branch = None
        if not run_command("git rev-parse --verify refs/remotes/origin/HEAD"):
            hash = get_output("git rev-parse refs/remotes/origin/HEAD")[0]
            for b in get_output("git for-each-ref --format='%(refname)' 'refs/remotes/origin/*'"):
                if get_output("git rev-parse %s" % b)[0] == hash:
                    branch = b
                    break
        if branch is None:
            if not run_command("git rev-parse --verify refs/remotes/origin/master"):
                branch = "refs/remotes/origin/master"
        if branch is None:
            branch = get_output("git for-each-ref --format='%(refname)' 'refs/remotes/origin/*'")
            branch = branch[0]

        hash = get_output("git rev-parse %s" % branch)
        assert hash
        branch = branch.replace('refs/remotes/origin/', '')
        run_safely("git update-ref refs/heads/%s %s" % (branch, hash[0]))
        run_safely("git symbolic-ref HEAD refs/heads/%s" % branch)
        self.cmd_revert(**{'-a': 1})

    @short_help("turn a directory into a repository")
    @long_help("""
Converts the current working directory into a repository.  The primary
side-effect of this command is the creation of a '.git' subdirectory.
No files are added nor commits made.
""")
    def cmd_init(self):
        os.system("git init")

    @short_help("add a new file to the repository")
    @long_help("""
The arguments are the files to be added to the repository.  Once added,
the files will show as "unstaged changes" in the output of 'status'.  To
reverse the effects of this command, see 'rm'.
""")
    def cmd_add(self, *files):
        "<file>..."
        if not files:
            raise TypeError
        
        for f in files:
            self._add_one(f)
        self.cmd_status()

    @short_help("delete a file from the repository")
    @long_help("""
The arguments are the files to be removed from the current revision of
the repository.  The files will still exist in any past commits that the
files may have been a part of.  The file is not actually deleted, it is
just no longer tracked as part of the repository.
""")
    def cmd_rm(self, *files):
        "<file>..."
        if not files:
            raise TypeError
        
        for f in files:
            self._rm_one(f)
        self.cmd_status()

    @short_help("stage changes in a file for commit")
    @long_help("""
The arguments are the files to be staged.  Staging changes is a way to
build up a commit when you do not want to commit all changes at once.
To commit only staged changes, use the '-d' flag to 'commit.'  To
reverse the effects of this command, see 'unstage'.  Once staged, the
files will show as "staged changes" in the output of 'status'.
""")
    def cmd_stage(self, *files):
        "<file>..."
        if not files:
            raise TypeError
        
        for f in files:
            self._stage_one(f)
        self.cmd_status()

    @short_help("unstage changes in a file")
    @long_help("""
The arguments are the files to be unstaged.  Once unstaged, the files
will show as "unstaged changes" in the output of 'status'.  The '-a'
flag can be used to unstage all staged changes at once.
""")
    @takes_options("a")
    def cmd_unstage(self, *files, **flags):
        "[-a] | <file>..."
        if '-a' in flags:
	    self._unstage_all()
            self.cmd_status()
            return

        if not files:
            raise TypeError
        
        for f in files:
            self._unstage_one(f)
        self.cmd_status()

    @short_help("show files with staged and unstaged changes")
    @long_help("""
Show the files in the repository with changes since the last commit,
categorized based on whether the changes are staged or not.  A file may
appear under each heading if the same file has both staged and unstaged
changes.
""")
    def cmd_status(self):
	""
        branch = get_output("git symbolic-ref HEAD")[0]
        branch = branch.replace('refs/heads/', '')
        print "Current branch: %s" % branch

        print "Files with staged changes:"
        files = self._get_staged_files()
        for f in files:
            print "\t%s" % f
        if not files:
            print "\t(none)"

        print "Files with unstaged changes:"
        files = self._get_unstaged_files()
        for f in files:
            print "\t%s" % f
        if not files:
            print "\t(none)"
	
	files = self._get_unmerged_files()
	if files:
	    print "Files with conflicts:"
	    for f in files:
		print "\t%s" % f

    @short_help("remove uncommitted changes from a file (*)")
    @long_help("""
The arguments are the files whose changes will be reverted.  If the '-a'
flag is given, then all files will have uncommitted changes removed.
Note that there is no way to reverse this command short of manually
editing each file again.
""")
    @takes_options("a")
    def cmd_revert(self, *files, **flags):
        "(-a | <file>)"
        if '-a' in flags:
	    self._unstage_all()
	    run_safely("git checkout-index -u -f -a")
	    self.cmd_status()
            return

        if not files:
            raise TypeError

        for f in files:
            self._revert_one(f)
        self.cmd_status()

    @short_help("record changes to files as a new commit")
    @long_help("""
Create a new commit recording changes since the last commit.  If there
are only unstaged changes, those will be recorded.  If there are only
staged changes, those will be recorded.  Otherwise, you will have to
specify either the '-a' flag or the '-d' flag to commit all changes or
only staged changes, respectively.  To reverse the effects of this
command, see 'uncommit'.
""")
    @takes_options("adm:")
    def cmd_commit(self, **flags):
	"[-a | -d]"
        self._check_rebasing()
        self._check_commit(**flags)
        if not self._get_staged_files():
            raise YapError("No changes to commit")
        msg = flags.get('-m', None)
        self._do_commit(msg)
        self.cmd_status()

    @short_help("reverse the actions of the last commit")
    @long_help("""
Reverse the effects of the last 'commit' operation.  The changes that
were part of the previous commit will show as "staged changes" in the
output of 'status'.  This means that if no files were changed since the
last commit was created, 'uncommit' followed by 'commit' is a lossless
operation.
""")
    def cmd_uncommit(self):
	""
        self._do_uncommit()
        self.cmd_status()

    @short_help("report the current version of yap")
    def cmd_version(self):
        print "Yap version 0.1"

    @short_help("show the changelog for particular versions or files")
    @long_help("""
The arguments are the files with which to filter history.  If none are
given, all changes are listed.  Otherwise only commits that affected one
or more of the given files are listed.  The -r option changes the
starting revision for traversing history.  By default, history is listed
starting at HEAD.
""")
    @takes_options("r:")
    def cmd_log(self, *paths, **flags):
        "[-r <rev>] <path>..."
        rev = flags.get('-r', 'HEAD')
        paths = ' '.join(paths)
        os.system("git log --name-status '%s' -- %s" % (rev, paths))

    @short_help("show staged, unstaged, or all uncommitted changes")
    @long_help("""
Show staged, unstaged, or all uncommitted changes.  By default, all
changes are shown.  The '-u' flag causes only unstaged changes to be
shown.  The '-d' flag causes only staged changes to be shown.
""")
    @takes_options("ud")
    def cmd_diff(self, **flags):
        "[ -u | -d ]"
        if '-u' in flags and '-d' in flags:
            raise YapError("Conflicting flags: -u and -d")

        pager = self._get_pager_cmd()

        if '-u' in flags:
            os.system("git diff-files -p | %s" % pager)
        elif '-d' in flags:
            os.system("git diff-index --cached -p HEAD | %s" % pager)
        else:
            os.system("git diff-index -p HEAD | %s" % pager)

    @short_help("list, create, or delete branches")
    @long_help("""
If no arguments are specified, a list of local branches is given.  The
current branch is indicated by a "*" next to the name.  If an argument
is given, it is taken as the name of a new branch to create.  The branch
will start pointing at the current HEAD.  See 'point' for details on
changing the revision of the new branch.  Note that this command does
not switch the current working branch.  See 'switch' for details on
changing the current working branch.

The '-d' flag can be used to delete local branches.  If the delete
operation would remove the last branch reference to a given line of
history (colloquially referred to as "dangling commits"), yap will
report an error and abort.  The '-f' flag can be used to force the delete
in spite of this.
""")
    @takes_options("fd:")
    def cmd_branch(self, branch=None, **flags):
        "[ [-f] -d <branch> | <branch> ]"
        force = '-f' in flags
        if '-d' in flags:
            self._delete_branch(flags['-d'], force)
            self.cmd_branch()
            return

        if branch is not None:
            ref = get_output("git rev-parse --verify HEAD")
            if not ref:
                raise YapError("No branch point yet.  Make a commit")
            run_safely("git update-ref 'refs/heads/%s' '%s'" % (branch, ref[0]))

        current = get_output("git symbolic-ref HEAD")[0]
        branches = get_output("git for-each-ref --format='%(refname)' 'refs/heads/*'")
        for b in branches:
            if b == current:
                print "* ",
            else:
                print "  ",
            b = b.replace('refs/heads/', '')
            print b

    @short_help("change the current working branch")
    @long_help("""
The argument is the name of the branch to make the current working
branch.  This command will fail if there are uncommitted changes to any
files.  Otherwise, the contents of the files in the working directory
are updated to reflect their state in the new branch.  Additionally, any
future commits are added to the new branch instead of the previous line
of history.
""")
    @takes_options("f")
    def cmd_switch(self, branch, **flags):
        "[-f] <branch>"
        ref = get_output("git rev-parse --verify 'refs/heads/%s'" % branch)
        if not ref:
            raise YapError("No such branch: %s" % branch)

	if '-f' not in flags and (self._get_unstaged_files() or self._get_staged_files()):
	    raise YapError("You have uncommitted changes.  Use -f to continue anyway")

	if self._get_unstaged_files() and self._get_staged_files():
	    raise YapError("You have staged and unstaged changes.  Perhaps unstage -a?")

	staged = bool(self._get_staged_files())

	run_command("git diff-files -p | git apply --cached")
	for f in self._get_new_files():
	    self._stage_one(f)

	idx = get_output("git write-tree")
	new = get_output("git rev-parse refs/heads/%s" % branch)
        run_safely("git read-tree --aggressive -u -m HEAD %s %s" % (idx[0], new[0]))
        run_safely("git symbolic-ref HEAD refs/heads/%s" % branch)

	if not staged:
	    self._unstage_all()
        self.cmd_status()

    @short_help("move the current branch to a different revision")
    @long_help("""
The argument is the hash of the commit to which the current branch
should point, or alternately a branch or tag (a.k.a, "committish").  If
moving the branch would create "dangling commits" (see 'branch'), yap
will report an error and abort.  The '-f' flag can be used to force the
operation in spite of this.
""")
    @takes_options("f")
    def cmd_point(self, where, **flags):
        "<where>"
        head = get_output("git rev-parse --verify HEAD")
        if not head:
            raise YapError("No commit yet; nowhere to point")

        ref = get_output("git rev-parse --verify '%s'" % where)
        if not ref:
            raise YapError("Not a valid ref: %s" % where)

        if self._get_unstaged_files() or self._get_staged_files():
            raise YapError("You have uncommitted changes.  Commit them first")

        type = get_output("git cat-file -t '%s'" % ref[0])
        if type and type[0] == "tag":
            tag = get_output("git cat-file tag '%s'" % ref[0])
            ref[0] = tag[0].split(' ')[1]

        run_safely("git update-ref HEAD '%s'" % ref[0])

        if '-f' not in flags:
            name = get_output("git name-rev --name-only '%s'" % head[0])[0]
            if name == "undefined":
                os.system("git update-ref HEAD '%s'" % head[0])
                raise YapError("Pointing there will lose commits.  Use -f to force")

        run_safely("git read-tree -u -m HEAD")
        run_safely("git checkout-index -u -f -a")

    @short_help("alter history by dropping or amending commits")
    @long_help("""
This command operates in two distinct modes, "amend" and "drop" mode.
In drop mode, the given commit is removed from the history of the
current branch, as though that commit never happened.  By default the
commit used is HEAD.

In amend mode, the uncommitted changes present are merged into a
previous commit.  This is useful for correcting typos or adding missed
files into past commits.  By default the commit used is HEAD.

While rewriting history it is possible that conflicts will arise.  If
this happens, the rewrite will pause and you will be prompted to resolve
the conflicts and stage them.  Once that is done, you will run "yap
history continue."  If instead you want the conflicting commit removed
from history (perhaps your changes supercede that commit) you can run
"yap history skip".  Once the rewrite completes, your branch will be on
the same commit as when the rewrite started.
""")
    def cmd_history(self, subcmd, *args):
        "amend | drop <commit>"

        if subcmd not in ("amend", "drop", "continue", "skip"):
            raise TypeError

        resolvemsg = """
When you have resolved the conflicts run \"yap history continue\".
To skip the problematic patch, run \"yap history skip\"."""

        if subcmd == "continue":
            os.system("git am -3 -r --resolvemsg='%s'" % resolvemsg)
            return
        if subcmd == "skip":
            os.system("git reset --hard")
            os.system("git am -3 --skip --resolvemsg='%s'" % resolvemsg)
            return

        if subcmd == "amend":
            flags, args = getopt.getopt(args, "ad")
            flags = dict(flags)

        if len(args) > 1:
            raise TypeError
        if args:
            commit = args[0]
        else:
            commit = "HEAD"

        if run_command("git rev-parse --verify '%s'" % commit):
            raise YapError("Not a valid commit: %s" % commit)

        self._check_rebasing()

        if subcmd == "amend":
            self._check_commit(**flags)
            if self._get_unstaged_files():
                # XXX: handle unstaged changes better
                raise YapError("Commit away changes that you aren't amending")

	stash = get_output("git stash create")
        try:
            run_command("git reset --hard")
	    fd, tmpfile = tempfile.mkstemp("yap")
	    try:
		try:
		    os.close(fd)
		    os.system("git format-patch -k --stdout '%s' > %s" % (commit, tmpfile))
		    if subcmd == "amend":
			self.cmd_point(commit, **{'-f': True})
		finally:
		    if subcmd == "amend":
			rc = os.system("git stash apply --index %s" % stash[0])
			if rc:
			    raise YapError("Failed to apply stash")
			stash = None

		if subcmd == "amend":
		    self._do_uncommit()
		    self._do_commit()
		else:
		    self.cmd_point("%s^" % commit, **{'-f': True})

		stat = os.stat(tmpfile)
		size = stat[6]
		if size > 0:
		    rc = os.system("git am -3 --resolvemsg=\'%s\' %s" % (resolvemsg, tmpfile))
		    if (rc):
			raise YapError("Failed to apply changes")
            finally:
		os.unlink(tmpfile)
        finally:
	    if stash:
		run_command("git stash apply --index %s" % stash[0])
        self.cmd_status()

    @short_help("show the changes introduced by a given commit")
    @long_help("""
By default, the changes in the last commit are shown.  To override this,
specify a hash, branch, or tag (committish).  The hash of the commit,
the commit's author, log message, and a diff of the changes are shown.
""")
    def cmd_show(self, commit="HEAD"):
        "[commit]"
        os.system("git show '%s'" % commit)

    @short_help("apply the changes in a given commit to the current branch")
    @long_help("""
The argument is the hash, branch, or tag (committish) of the commit to
be applied.  In general, it only makes sense to apply commits that
happened on another branch.  The '-r' flag can be used to have the
changes in the given commit reversed from the current branch.  In
general, this only makes sense for commits that happened on the current
branch.
""")
    @takes_options("r")
    def cmd_cherry_pick(self, commit, **flags):
        "[-r] <commit>"
        if '-r' in flags:
            os.system("git revert '%s'" % commit)
        else:
            os.system("git cherry-pick '%s'" % commit)

    @short_help("list, add, or delete configured remote repositories")
    @long_help("""
When invoked with no arguments, this command will show the list of
currently configured remote repositories, giving both the name and URL
of each.  To add a new repository, give the desired name as the first
argument and the URL as the second.  The '-d' flag can be used to remove
a previously added repository.
""")
    @takes_options("d:")
    def cmd_repo(self, name=None, url=None, **flags):
        "[<name> <url> | -d <name>]"
        if name is not None and url is None:
            raise TypeError

        if '-d' in flags:
            if flags['-d'] not in [ x[0] for x in self._list_remotes() ]:
                raise YapError("No such repository: %s" % flags['-d'])
            os.system("git config --unset remote.%s.url" % flags['-d'])
            os.system("git config --unset remote.%s.fetch" % flags['-d'])

        if name:
            if name in [ x[0] for x in self._list_remotes() ]:
                raise YapError("Repository '%s' already exists" % flags['-d'])
            os.system("git config remote.%s.url %s" % (name, url))
            os.system("git config remote.%s.fetch +refs/heads/*:refs/remotes/%s/*" % (name, name))

        for remote, url in self._list_remotes():
	    print "%-20s %s" % (remote, url)
    
    @takes_options("cd")
    @short_help("send local commits to a remote repository")
    def cmd_push(self, repo, **flags):
	"[-c | -d] <repo>"

	if repo not in [ x[0] for x in self._list_remotes() ]:
	    raise YapError("No such repository: %s" % repo)

        current = get_output("git symbolic-ref HEAD")
        if not current:
            raise YapError("Not on a branch!")
	ref = current[0]
	current = current[0].replace('refs/heads/', '')
	remote = get_output("git config branch.%s.remote" % current)
	if remote and remote[0] == repo:
	    merge = get_output("git config branch.%s.merge" % current)
	    if merge:
		ref = merge[0]
	
	if '-c' not in flags and '-d' not in flags:
	    if run_command("git rev-parse --verify refs/remotes/%s/%s"
		    % (repo, ref.replace('refs/heads/', ''))):
		raise YapError("No matching branch on that repo.  Use -c to create a new branch there.")
	
	if '-d' in flags:
	    lhs = ""
	else:
	    lhs = "refs/heads/%s" % current
	rc = os.system("git push %s %s:%s" % (repo, lhs, ref))
	if rc:
	    raise YapError("Push failed.")

    @short_help("retrieve commits from a remote repository")
    def cmd_fetch(self, repo):
        "<repo>"
	# XXX allow defaulting of repo? yap.default
	if repo not in [ x[0] for x in self._list_remotes() ]:
	    raise YapError("No such repository: %s" % repo)
	os.system("git fetch %s" % repo)

    @short_help("update the current branch relative to its tracking branch")
    def cmd_update(self, subcmd=None):
        "[continue | skip]"
        if subcmd and subcmd not in ["continue", "skip"]:
            raise TypeError

        resolvemsg = """
When you have resolved the conflicts run \"yap history continue\".
To skip the problematic patch, run \"yap history skip\"."""

        if subcmd == "continue":
            os.system("git am -3 -r --resolvemsg='%s'" % resolvemsg)
            return
        if subcmd == "skip":
            os.system("git reset --hard")
            os.system("git am -3 --skip --resolvemsg='%s'" % resolvemsg)
            return

        self._check_rebasing()
        if self._get_unstaged_files() or self._get_staged_files():
            raise YapError("You have uncommitted changes.  Commit them first")

        current = get_output("git symbolic-ref HEAD")
        if not current:
            raise YapError("Not on a branch!")

	current = current[0].replace('refs/heads/', '')
        remote, merge = self._get_tracking(current)
        merge = merge[0].replace('refs/heads/', '')

        self.cmd_fetch(remote)
        base = get_output("git merge-base HEAD refs/remotes/%s/%s" % (remote, merge))

        try:
            fd, tmpfile = tempfile.mkstemp("yap")
            os.close(fd)
            os.system("git format-patch -k --stdout '%s' > %s" % (base[0], tmpfile))
            self.cmd_point("refs/remotes/%s/%s" % (remote, merge), **{'-f': True})

            stat = os.stat(tmpfile)
            size = stat[6]
            if size > 0:
                rc = os.system("git am -3 --resolvemsg=\'%s\' %s" % (resolvemsg, tmpfile))
                if (rc):
                    raise YapError("Failed to apply changes")
        finally:
            os.unlink(tmpfile)

    @short_help("query and configure remote branch tracking")
    def cmd_track(self, repo=None, branch=None):
        "[<repo> <branch>]"

        current = get_output("git symbolic-ref HEAD")
        if not current:
            raise YapError("Not on a branch!")
	current = current[0].replace('refs/heads/', '')

        if repo is None and branch is None:
            repo, merge = self._get_tracking(current)
            merge = merge[0].replace('refs/heads/', '')
            print "Branch '%s' tracking refs/remotes/%s/%s" % (current, repo, merge)
            return

        if repo is None or branch is None:
            raise TypeError

        if repo not in [ x[0] for x in self._list_remotes() ]:
            raise YapError("No such repository: %s" % repo)

        if run_command("git rev-parse --verify refs/remotes/%s/%s" % (repo, branch)):
            raise YapError("No such branch '%s' on repository '%s'" % (repo, branch))

        os.system("git config branch.%s.remote '%s'" % (current, repo))
        os.system("git config branch.%s.merge 'refs/heads/%s'" % (current, branch))
        print "Branch '%s' now tracking refs/remotes/%s/%s" % (current, repo, branch)

    def cmd_help(self, cmd=None):
        if cmd is not None:
            try:
                attr = self.__getattribute__("cmd_"+cmd.replace('-', '_'))
            except AttributeError:
                raise YapError("No such command: %s" % cmd)
            try:
                help = attr.long_help
            except AttributeError:
                raise YapError("Sorry, no help for '%s'.  Ask Steven." % cmd)

            print >>sys.stderr, "The '%s' command" % cmd
            print >>sys.stderr, "\tyap %s %s" % (cmd, attr.__doc__)
            print >>sys.stderr, "%s" % help
            return

        print >> sys.stderr, "Yet Another (Git) Porcelein"
        print >> sys.stderr

        for name in dir(self):
            if not name.startswith('cmd_'):
                continue
            attr = self.__getattribute__(name)
            if not callable(attr):
                continue
            try:
                short_msg = attr.short_help
            except AttributeError:
                continue

            name = name.replace('cmd_', '')
            name = name.replace('_', '-')
            print >> sys.stderr, "%-16s%s" % (name, short_msg)
	print >> sys.stderr
	print >> sys.stderr, "(*) Indicates that the command is not readily reversible"

    def cmd_usage(self):
        print >> sys.stderr, "usage: %s <command>" % os.path.basename(sys.argv[0])
        print >> sys.stderr, "  valid commands: help init clone add rm stage unstage status revert commit uncommit log show diff branch switch point cherry-pick repo track push fetch update history version"

    def main(self, args):
        if len(args) < 1:
            self.cmd_usage()
            sys.exit(2)

        command = args[0]
        args = args[1:]

        debug = os.getenv('YAP_DEBUG')

        try:
            command = command.replace('-', '_')

            meth = None
            for p in self.plugins:
                try:
                    meth = p.__getattribute__("cmd_"+command)
                except AttributeError:
                    continue

            try:
                default_meth = self.__getattribute__("cmd_"+command)
            except AttributeError:
                default_meth = None

            if meth is None:
                meth = default_meth
            if meth is None:
                raise AttributeError

            try:
                if "options" in meth.__dict__:
                    options = meth.options
                    if default_meth and "options" in default_meth.__dict__:
                        options += default_meth.options
                    flags, args = getopt.getopt(args, options)
                    flags = dict(flags)
                else:
                    flags = dict()

                # invoke pre-hooks
                for p in self.plugins:
                    try:
                        meth = p.__getattribute__("pre_"+command)
                    except AttributeError:
                        continue
                    meth(*args, **flags)

                meth(*args, **flags)

                # invoke post-hooks
                for p in self.plugins:
                    try:
                        meth = p.__getattribute__("post_"+command)
                    except AttributeError:
                        continue
                    meth()

            except (TypeError, getopt.GetoptError):
                if debug:
                    raise
                print "%s %s %s" % (sys.argv[0], command, meth.__doc__)
            except YapError, e:
                print >> sys.stderr, e
                sys.exit(1)
        except AttributeError:
            if debug:
                raise
            self.cmd_usage()
            sys.exit(2)
