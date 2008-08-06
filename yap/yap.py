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
        self.plugins = dict()
        self.overrides = []
        plugindir = os.path.expanduser("~/.yap/plugins")
        for p in glob.glob(os.path.join(plugindir, "*.py")):
            glbls = {}
            execfile(p, glbls)
            for k, cls in glbls.items():
                if not type(cls) == type:
                    continue
                if not issubclass(cls, YapPlugin):
                    continue
                if cls is YapPlugin:
                    continue
                x = cls(self)

                for func in dir(x):
                    if not func.startswith('cmd_'):
                        continue
                    if func in self.overrides:
                        print >>sys.stderr, "Plugin %s overrides already overridden function %s.  Disabling" % (p, func)
                        break
		self.plugins[k] = x

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
	try:
	    pickle.dump(files, open(path, 'w'))
	except IOError:
	    pass

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
        current = get_output("git symbolic-ref HEAD")
	if current:
	    current = current[0].replace('refs/heads/', '')
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

    def _stage_one(self, file, allow_unmerged=False):
        self._assert_file_exists(file)
	prefix = get_output("git rev-parse --show-prefix")
	if prefix:
	    tmp = os.path.normpath(os.path.join(prefix[0], file))
	else:
	    tmp = file
	if not allow_unmerged and tmp in self._get_unmerged_files():
	    raise YapError("Refusing to stage conflicted file: %s" % file)
        run_safely("git update-index --add '%s'" % file)

    def _unstage_one(self, file):
        self._assert_file_exists(file)
        if run_command("git rev-parse HEAD"):
            rc = run_command("git update-index --force-remove '%s'" % file)
        else:
            rc = run_command("git diff-index --cached -p HEAD '%s' | git apply -R --cached" % file)
        if rc:
            raise YapError("Failed to unstage")

    def _revert_one(self, file):
        self._assert_file_exists(file)
        try:
            self._unstage_one(file)
        except YapError:
            pass
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

	repo = get_output('git rev-parse --git-dir')[0]
	head_file = os.path.join(repo, 'yap', 'merge')
	try:
	    parent = pickle.load(file(head_file))
	except IOError:
	    parent = get_output("git rev-parse --verify HEAD 2> /dev/null")

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

        if parent:
	    parent = ' -p '.join(parent)
            commit = get_output("git commit-tree '%s' -p %s < '%s'" % (tree, parent, tmpfile))
        else:
            commit = get_output("git commit-tree '%s' < '%s'" % (tree, tmpfile))

        os.unlink(tmpfile)
        run_safely("git update-ref HEAD '%s'" % commit[0])
	self._clear_state()

    def _check_rebasing(self):
        repo = get_output('git rev-parse --git-dir')[0]
        dotest = os.path.join(repo, '.dotest')
        if os.access(dotest, os.R_OK):
            raise YapError("A git operation is in progress.  Complete it first")
        dotest = os.path.join(repo, '..', '.dotest')
        if os.access(dotest, os.R_OK):
            raise YapError("A git operation is in progress.  Complete it first")

    def _check_git(self):
	if run_command("git rev-parse --git-dir"):
	    raise YapError("That command must be run from inside a git repository")

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
        return remote[0], merge[0]

    def __getattribute__(self, attr):
	if attr.startswith("cmd_"):
            meth = None
            for p in self.plugins.values():
                try:
                    meth = p.__getattribute__(attr)
		    break
                except AttributeError:
                    continue

	    if meth:
		return meth
	return super(Yap, self).__getattribute__(attr)

    def _call_base(self, method, *args, **flags):
	base_method = super(Yap, self).__getattribute__(method)
	return base_method(*args, **flags)
    def _confirm_push(self, current, rhs, repo):
        print "About to push local branch '%s' to '%s' on '%s'" % (current, rhs, repo)
        print "Continue (y/n)? ",
        sys.stdout.flush()
        ans = sys.stdin.readline().strip()

        if ans.lower() != 'y' and ans.lower() != 'yes':
            raise YapError("Aborted.")

    def _clear_state(self):
	repo = get_output('git rev-parse --git-dir')[0]
        dir = os.path.join(repo, 'yap')
	try:
	    os.unlink(os.path.join(dir, 'new-files'))
	    os.unlink(os.path.join(dir, 'merge'))
	    os.unlink(os.path.join(dir, 'msg'))
	except OSError:
	    pass

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
        self._check_git()

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
        self._check_git()
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
        self._check_git()
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
        self._check_git()
        if '-a' in flags:
	    files = self._get_staged_files()

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
        self._check_git()
        branch = get_output("git symbolic-ref HEAD")
	if branch:
	    branch = branch[0].replace('refs/heads/', '')
	else:
	    branch = "DETACHED"
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
        self._check_git()
        if '-a' in flags:
	    self._unstage_all()
	    run_safely("git checkout-index -u -f -a")
	    self._clear_state()
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
	"[-a | -d] [-m <msg>]"
        self._check_git()
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
        self._check_git()
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
    @takes_options("pr:")
    def cmd_log(self, *paths, **flags):
        "[-p] [-r <rev>] <path>..."
        self._check_git()
        rev = flags.get('-r', 'HEAD')

	if '-p' in flags:
	    flags['-p'] = '-p'

	if len(paths) == 1:
	    follow = "--follow"
	else:
	    follow = ""
        paths = ' '.join(paths)
	os.system("git log -M -C %s %s '%s' -- %s"
		% (follow, flags.get('-p', '--name-status'), rev, paths))

    @short_help("show staged, unstaged, or all uncommitted changes")
    @long_help("""
Show staged, unstaged, or all uncommitted changes.  By default, all
changes are shown.  The '-u' flag causes only unstaged changes to be
shown.  The '-d' flag causes only staged changes to be shown.
""")
    @takes_options("ud")
    def cmd_diff(self, **flags):
        "[ -u | -d ]"
        self._check_git()
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
        self._check_git()
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

        current = get_output("git symbolic-ref HEAD")
        branches = get_output("git for-each-ref --format='%(refname)' 'refs/heads/*'")
        for b in branches:
            if current and b == current[0]:
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
        self._check_git()
        self._check_rebasing()
        ref = get_output("git rev-parse --verify 'refs/heads/%s'" % branch)
        if not ref:
            raise YapError("No such branch: %s" % branch)

	if '-f' not in flags:
	    if (self._get_staged_files() 
		    or (self._get_unstaged_files() 
			and run_command("git update-index --refresh"))):
		raise YapError("You have uncommitted changes.  Use -f to continue anyway")

	if self._get_unstaged_files() and self._get_staged_files():
	    raise YapError("You have staged and unstaged changes.  Perhaps unstage -a?")

	staged = bool(self._get_staged_files())

	run_command("git diff-files -p | git apply --cached")
	for f in self._get_new_files():
	    self._stage_one(f)

	idx = get_output("git write-tree")
	new = get_output("git rev-parse refs/heads/%s" % branch)
	readtree = "git read-tree --aggressive -u -m HEAD %s %s" % (idx[0], new[0])
	if run_command(readtree):
	    run_command("git update-index --refresh")
	    if os.system(readtree):
		raise YapError("Failed to switch")
        run_safely("git symbolic-ref HEAD refs/heads/%s" % branch)

	if '-f' not in flags:
	    self._clear_state()

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
        "[-f] <where>"
        self._check_git()
        self._check_rebasing()

        head = get_output("git rev-parse --verify HEAD")
        if not head:
            raise YapError("No commit yet; nowhere to point")

        ref = get_output("git rev-parse --verify '%s^{commit}'" % where)
        if not ref:
            raise YapError("Not a valid ref: %s" % where)

        if self._get_unstaged_files() or self._get_staged_files():
            raise YapError("You have uncommitted changes.  Commit them first")

        run_safely("git update-ref HEAD '%s'" % ref[0])

        if '-f' not in flags:
            name = get_output("git name-rev --name-only '%s'" % head[0])[0]
            if name == "undefined":
                os.system("git update-ref HEAD '%s'" % head[0])
                raise YapError("Pointing there will lose commits.  Use -f to force")

        try:
            run_safely("git read-tree -u -m HEAD")
        except ShellError:
            run_safely("git read-tree HEAD")
	    run_safely("git checkout-index -u -f -a")
	self._clear_state()

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
        self._check_git()

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

        self._unstage_all()

        start = get_output("git rev-parse HEAD")
	stash = get_output("git stash create")
        run_command("git reset --hard")
        try:
	    fd, tmpfile = tempfile.mkstemp("yap")
	    try:
		try:
		    os.close(fd)
		    os.system("git format-patch -k --stdout '%s' > %s" % (commit, tmpfile))
		    if subcmd == "amend":
			self.cmd_point(commit, **{'-f': True})
		finally:
		    if subcmd == "amend":
			if stash:
			    rc = os.system("git stash apply %s" % stash[0])
			    if rc:
				self.cmd_point(start[0], **{'-f': True})
				os.system("git stash apply %s" % stash[0])
				raise YapError("Failed to apply stash")
			stash = None

		if subcmd == "amend":
		    self._do_uncommit()
		    self._check_commit(**{'-a': True})
		    self._do_commit()
		else:
		    self.cmd_point("%s^" % commit, **{'-f': True})

		stat = os.stat(tmpfile)
		size = stat[6]
		if size > 0:
		    run_safely("git update-index --refresh")
		    rc = os.system("git am -3 --resolvemsg=\'%s\' %s" % (resolvemsg, tmpfile))
		    if (rc):
			raise YapError("Failed to apply changes")
            finally:
		os.unlink(tmpfile)
        finally:
	    if stash:
		run_command("git stash apply %s" % stash[0])
        self.cmd_status()

    @short_help("show the changes introduced by a given commit")
    @long_help("""
By default, the changes in the last commit are shown.  To override this,
specify a hash, branch, or tag (committish).  The hash of the commit,
the commit's author, log message, and a diff of the changes are shown.
""")
    def cmd_show(self, commit="HEAD"):
        "[commit]"
        self._check_git()
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
        self._check_git()
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
        self._check_git()
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
    
    @short_help("send local commits to a remote repository (*)")
    @long_help("""
When invoked with no arguments, the current branch is synchronized to
the tracking branch of the tracking remote.  If no tracking remote is
specified, the repository will have to be specified on the command line.
In that case, the default is to push to a branch with the same name as
the current branch.  This behavior can be overridden by giving a second
argument to specify the remote branch.

If the remote branch does not currently exist, the command will abort
unless the -c flag is provided.  If the remote branch is not a direct
descendent of the local branch, the command will abort unless the -f
flag is provided.  Forcing a push in this way can be problematic to
other users of the repository if they are not expecting it.

To delete a branch on the remote repository, use the -d flag.
""")
    @takes_options("cdf")
    def cmd_push(self, repo=None, rhs=None, **flags):
	"[-c | -d] <repo>"
        self._check_git()
        if '-c' in flags and '-d' in flags:
            raise TypeError

	if repo and repo not in [ x[0] for x in self._list_remotes() ]:
	    raise YapError("No such repository: %s" % repo)

        current = get_output("git symbolic-ref HEAD")
        if not current:
            raise YapError("Not on a branch!")

        self._check_rebasing()

	current = current[0].replace('refs/heads/', '')
	remote = get_output("git config branch.%s.remote" % current)
        if repo is None and remote:
            repo = remote[0]

        if repo is None:
            raise YapError("No tracking branch configured; specify destination repository")

	if rhs is None and remote and remote[0] == repo:
	    merge = get_output("git config branch.%s.merge" % current)
	    if merge:
		rhs = merge[0]
	
        if rhs is None:
            rhs = "refs/heads/%s" % current

	if '-c' not in flags and '-d' not in flags:
	    if run_command("git rev-parse --verify refs/remotes/%s/%s"
		    % (repo, rhs.replace('refs/heads/', ''))):
		raise YapError("No matching branch on that repo.  Use -c to create a new branch there.")
            if '-f' not in flags:
                hash = get_output("git rev-parse refs/remotes/%s/%s" % (repo, rhs.replace('refs/heads/', '')))
                base = get_output("git merge-base HEAD %s" % hash[0])
                assert base
                if base[0] != hash[0]:
                    raise YapError("Branch not up-to-date with remote.  Update or use -f")

	self._confirm_push(current, rhs, repo)
        if '-f' in flags:
            flags['-f'] = '-f'
	
	if '-d' in flags:
	    lhs = ""
	else:
	    lhs = "refs/heads/%s" % current
	rc = os.system("git push %s %s %s:%s" % (flags.get('-f', ''), repo, lhs, rhs))
	if rc:
	    raise YapError("Push failed.")

    @short_help("retrieve commits from a remote repository")
    @long_help("""
When run with no arguments, the command will retrieve new commits from
the remote tracking repository.  Note that this does not in any way
alter the current branch.  For that, see "update".  If a remote other
than the tracking remote is desired, it can be specified as the first
argument.
""")
    def cmd_fetch(self, repo=None):
        "<repo>"
        self._check_git()
        current = get_output("git symbolic-ref HEAD")
        if not current:
            raise YapError("Not on a branch!")

	if repo and repo not in [ x[0] for x in self._list_remotes() ]:
	    raise YapError("No such repository: %s" % repo)
        if repo is None:
            current = current[0].replace('refs/heads/', '')
            remote = get_output("git config branch.%s.remote" % current)
            if remote:
                repo = remote[0]
        if repo is None:
            raise YapError("No tracking branch configured; specify a repository")
	os.system("git fetch %s" % repo)

    @short_help("update the current branch relative to its tracking branch")
    @long_help("""
Updates the current branch relative to its remote tracking branch.  This
command requires that the current branch have a remote tracking branch
configured.  If any conflicts occur while applying your changes to the
updated remote, the command will pause to allow you to fix them.  Once
that is done, run "update" with the "continue" subcommand.  Alternately,
the "skip" subcommand can be used to discard the conflicting changes.
""")
    def cmd_update(self, subcmd=None):
        "[continue | skip]"
        self._check_git()
        if subcmd and subcmd not in ["continue", "skip"]:
            raise TypeError

        resolvemsg = """
When you have resolved the conflicts run \"yap update continue\".
To skip the problematic patch, run \"yap update skip\"."""

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
        merge = merge.replace('refs/heads/', '')

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
    @long_help("""
When invoked with no arguments, the command displays the tracking
information for the current branch.  To configure the tracking
information, two arguments for the remote repository and remote branch
are given.  The tracking information is used to provide defaults for
where to push local changes and from where to get updates to the branch.
""")
    def cmd_track(self, repo=None, branch=None):
        "[<repo> <branch>]"
        self._check_git()

        current = get_output("git symbolic-ref HEAD")
        if not current:
            raise YapError("Not on a branch!")
	current = current[0].replace('refs/heads/', '')

        if repo is None and branch is None:
            repo, merge = self._get_tracking(current)
            merge = merge.replace('refs/heads/', '')
            print "Branch '%s' tracking refs/remotes/%s/%s" % (current, repo, merge)
            return

        if repo is None or branch is None:
            raise TypeError

        if repo not in [ x[0] for x in self._list_remotes() ]:
            raise YapError("No such repository: %s" % repo)

        if run_command("git rev-parse --verify refs/remotes/%s/%s" % (repo, branch)):
            raise YapError("No such branch '%s' on repository '%s'" % (branch, repo))

        os.system("git config branch.%s.remote '%s'" % (current, repo))
        os.system("git config branch.%s.merge 'refs/heads/%s'" % (current, branch))
        print "Branch '%s' now tracking refs/remotes/%s/%s" % (current, repo, branch)

    @short_help("mark files with conflicts as resolved")
    @long_help("""
The arguments are the files to be marked resolved.  When a conflict
occurs while merging changes to a file, that file is marked as
"unmerged."  Until the file(s) with conflicts are marked resolved,
commits cannot be made.
""")
    def cmd_resolved(self, *files):
        "<file>..."
        self._check_git()
        if not files:
            raise TypeError
        
        for f in files:
            self._stage_one(f, True)
        self.cmd_status()

    @short_help("merge a branch into the current branch")
    def cmd_merge(self, branch):
	"<branch>"
        self._check_git()

	branch_name = branch
	branch = get_output("git rev-parse --verify %s" % branch)
	if not branch:
	    raise YapError("No such branch: %s" % branch)
	branch = branch[0]

	base = get_output("git merge-base HEAD %s" % branch)
	if not base:
	    raise YapError("Branch '%s' is not a fork of the current branch"
		    % branch)

	readtree = ("git read-tree --aggressive -u -m %s HEAD %s"
		% (base[0], branch))
	if run_command(readtree):
	    run_command("git update-index --refresh")
	    if os.system(readtree):
		raise YapError("Failed to merge")

	repo = get_output('git rev-parse --git-dir')[0]
        dir = os.path.join(repo, 'yap')
        try:
            os.mkdir(dir)
        except OSError:
            pass
	msg_file = os.path.join(dir, 'msg')
	msg = file(msg_file, 'w')
	print >>msg, "Merge branch '%s'" % branch_name
	msg.close()

	head = get_output("git rev-parse --verify HEAD")
	assert head
	heads = [head[0], branch]
	head_file = os.path.join(dir, 'merge')
	pickle.dump(heads, file(head_file, 'w'))

	self._merge_index(branch, base[0])
	if self._get_unmerged_files():
	    self.cmd_status()
	    raise YapError("Fix conflicts then commit")

	self._do_commit()

    def _merge_index(self, branch, base):
	for f in self._get_unmerged_files():
	    fd, bfile = tempfile.mkstemp("yap")
	    os.close(fd)
	    rc = os.system("git show %s:%s > %s" % (base, f, bfile))
	    assert rc == 0

	    fd, ofile = tempfile.mkstemp("yap")
	    os.close(fd)
	    rc = os.system("git show %s:%s > %s" % (branch, f, ofile))
	    assert rc == 0

	    command = "git merge-file -L %(file)s -L %(file)s.base -L %(file)s.%(branch)s %(file)s %(base)s %(other)s " % dict(file=f, branch=branch, base=bfile, other=ofile)
	    rc = os.system(command)
	    os.unlink(ofile)
	    os.unlink(bfile)

	    assert rc >= 0
	    if rc == 0:
		self._stage_one(f, True)

    @short_help("show information about loaded plugins")
    def cmd_plugins(self):
	""
	if not self.plugins:
	    print >>sys.stderr, "No plugins loaded."
	for k, v in self.plugins.items():
	    doc = v.__doc__
	    if doc is None:
		doc = "No description"
	    print "%-20s%s" % (k, doc)
	    first = True
	    for func in dir(v):
		if not func.startswith('cmd_'):
		    continue
		if first is True:
		    print "\tOverrides:"
		    first = False
		print "\t%s" % func

    def cmd_help(self, cmd=None):
        if cmd is not None:
            cmd = "cmd_" + cmd.replace('-', '_')
            try:
                attr = self.__getattribute__(cmd)
            except AttributeError:
                raise YapError("No such command: %s" % cmd)
            try:
                help = attr.long_help
            except AttributeError:
                attr = super(Yap, self).__getattribute__(cmd)
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
		try:
		    default_meth = super(Yap, self).__getattribute__(name)
		    short_msg = default_meth.short_help
		except AttributeError:
		    continue

            name = name.replace('cmd_', '')
            name = name.replace('_', '-')
            print >> sys.stderr, "%-16s%s" % (name, short_msg)
	
	print >> sys.stderr
	print >> sys.stderr, "Commands provided by plugins:"
	for k, v in self.plugins.items():
	    for name in dir(v):
		if not name.startswith('cmd_'):
		    continue
		try:
		    attr = self.__getattribute__(name)
		    short_msg = attr.short_help
		except AttributeError:
		    continue
		name = name.replace('cmd_', '')
		name = name.replace('_', '-')
		print >> sys.stderr, "%-8s(%s) %s" % (name, k, short_msg)

	print >> sys.stderr
	print >> sys.stderr, "(*) Indicates that the command is not readily reversible"

    def cmd_usage(self):
        print >> sys.stderr, "usage: %s <command>" % os.path.basename(sys.argv[0])
        print >> sys.stderr, "  valid commands: help init clone add rm stage unstage status revert commit uncommit log show diff branch switch point cherry-pick repo track push fetch update history resolved plugins version"

    def main(self, args):
        if len(args) < 1:
            self.cmd_usage()
            sys.exit(2)

        command = args[0]
        args = args[1:]

	if run_command("git --version"):
	    print >>sys.stderr, "Failed to run git; is it installed?"
	    sys.exit(1)

        debug = os.getenv('YAP_DEBUG')

        try:
            command = command.replace('-', '_')

	    meth = self.__getattribute__("cmd_"+command)
	    try:
		default_meth = super(Yap, self).__getattribute__("cmd_"+command)
	    except AttributeError:
		default_meth = None

	    if meth.__doc__ is not None:
		doc = meth.__doc__
	    elif default_meth is not None:
		doc = default_meth.__doc__
	    else:
		doc = ""

            try:
                options = ""
                if "options" in meth.__dict__:
                    options = meth.options
                if default_meth and "options" in default_meth.__dict__:
                    options += default_meth.options
                if options:
                    flags, args = getopt.getopt(args, options)
                    flags = dict(flags)
                else:
                    flags = dict()

		# cast args to a mutable type.  this lets the pre-hooks act as
		# filters on the arguments
		args = list(args)

                # invoke pre-hooks
                for p in self.plugins.values():
                    try:
                        pre_meth = p.__getattribute__("pre_"+command)
                    except AttributeError:
                        continue
                    pre_meth(args, flags)

                meth(*args, **flags)

                # invoke post-hooks
                for p in self.plugins.values():
                    try:
                        meth = p.__getattribute__("post_"+command)
                    except AttributeError:
                        continue
                    meth()

            except (TypeError, getopt.GetoptError):
                if debug:
                    raise
		print "Usage: %s %s %s" % (os.path.basename(sys.argv[0]), command, doc)
            except YapError, e:
                if debug:
                    raise
                print >> sys.stderr, e
                sys.exit(1)
        except AttributeError:
            if debug:
                raise
            self.cmd_usage()
            sys.exit(2)
