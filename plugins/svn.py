
from yap import YapPlugin, YapError
from yap.util import get_output, takes_options, run_command, run_safely, short_help
import os

class SvnPlugin(YapPlugin):
    def __init__(self, yap):
        self.yap = yap

    def _get_root(self, url):
        root = get_output("svn info %s 2>/dev/null | gawk '/Repository Root:/{print $3}'" % url)
        if not root:
            raise YapError("Not an SVN repo: %s" % url)
        return root[0]

    def _configure_repo(self, url):
        root = self._get_root(url)
        os.system("git config svn-remote.svn.url %s" % root)
        trunk = url.replace(root, '').strip('/')
        os.system("git config svn-remote.svn.fetch %s:refs/remotes/svn/trunk"
                % trunk)
        branches = trunk.replace('trunk', 'branches')
        os.system("git config svn-remote.svn.branches %s/*:refs/remotes/svn/*"
                % branches)
        tags = trunk.replace('trunk', 'tags')
        os.system("git config svn-remote.svn.tags %s/*:refs/tags/*" % tags)
        self.yap.cmd_repo("svn", url)
        os.system("git config yap.svn.enabled 1")

    def _clone_svn(self, url, directory=None, **flags):
        url = url.rstrip('/')
        if directory is None:
            directory = url.rsplit('/')[-1]
            directory = directory.replace('.git', '')

        try:
            os.mkdir(directory)
        except OSError:
            raise YapError("Directory exists: %s" % directory)
        os.chdir(directory)

        self.yap.cmd_init()
        self._configure_repo(url)
	os.system("git svn fetch -r %s:HEAD" % flags.get('-r', '1'))

    def _push_svn(self, branch):
	print "Verifying branch is up-to-date"
	self.yap.cmd_fetch("svn")

        branch = branch.replace('refs/heads/', '')
	rev = get_output("git rev-parse refs/remotes/svn/%s" % branch)
        if not rev:
            raise YapError("Creating svn branches not yet supported")

	base = get_output("git merge-base HEAD %s" % rev[0])
	if base[0] != rev[0]:
	    raise YapError("Branch not up-to-date.  Update first.")
	current = get_output("git symbolic-ref HEAD")
	if not current:
	    raise YapError("Not on a branch!")
	current = current[0].replace('refs/heads/', '')
	self.yap._confirm_push(current, "trunk", "svn")
	if run_command("git update-index --refresh"):
	    raise YapError("Can't push with uncommitted changes")

	master = get_output("git rev-parse --verify refs/heads/master")
	os.system("git svn dcommit")
	run_safely("git svn rebase")
	if not master:
	    master = get_output("git rev-parse --verify refs/heads/master")
	    if master:
		run_safely("git update-ref -d refs/heads/master %s" % master[0])

    def _enabled(self):
	enabled = get_output("git config yap.svn.enabled")
	return bool(enabled)

    # Ensure users don't accidentally kill our "svn" repo
    def pre_repo(self, *args, **flags):
	if not self._enabled():
	    return
        if '-d' in flags and args and args[0] == "svn":
	    raise YapError("Refusing to delete special svn repository")

    @takes_options("r:")
    def cmd_clone(self, *args, **flags):
        if args and not run_command("svn info %s" % args[0]):
            self._clone_svn(*args, **flags)
        else:
            self.yap._call_base("cmd_commit", *args, **flags)

    def cmd_fetch(self, *args, **flags):
	if self._enabled():
	    if args and args[0] == 'svn':
		os.system("git svn fetch svn")
		return
            elif not args:
                current = get_output("git symbolic-ref HEAD")
                if not current:
                    raise YapError("Not on a branch!")

                current = current[0].replace('refs/heads/', '')
                remote, merge = self.yap._get_tracking(current)
                if remote == "svn":
                    os.system("git svn fetch svn")
                    return
	self.yap._call_base("cmd_fetch", *args, **flags)

    def cmd_push(self, *args, **flags):
	if self._enabled():
	    if args and args[0] == 'svn':
                if len (args) < 2:
                    raise YapError("Need a branch name")
		self._push_svn(args[1])
		return
            elif not args:
                current = get_output("git symbolic-ref HEAD")
                if not current:
                    raise YapError("Not on a branch!")

                current = current[0].replace('refs/heads/', '')
                remote, merge = self.yap._get_tracking(current)
                if remote == "svn":
                    self._push_svn(merge)
                    return

	self.yap._call_base("cmd_push", *args, **flags)

    @short_help("change options for the svn plugin")
    def cmd_svn(self, subcmd):
	"enable"

	if subcmd not in ["enable"]:
	    raise TypeError

	if "svn" in [x[0] for x in self.yap._list_remotes()]:
	    raise YapError("A remote named 'svn' already exists")


        if not run_command("git config svn-remote.svn.branches"):
            raise YapError("Cannot currently enable in a repository with svn branches")

        url = get_output("git config svn-remote.svn.url")
        if not url:
            raise YapError("Not a git-svn repository?")
        fetch = get_output("git config svn-remote.svn.fetch")
        assert fetch
        lhs, rhs = fetch[0].split(':')


        rev = get_output("git rev-parse %s" % rhs)
        assert rev
        run_safely("git update-ref refs/remotes/svn/trunk %s" % rev[0])

        url = '/'.join((url[0], lhs))
        self._configure_repo(url)
        run_safely("git update-ref -d %s %s" % (rhs, rev[0]))
