
from yap import YapPlugin, YapError
from yap.util import get_output, takes_options, run_command, run_safely, short_help
import os

class SvnPlugin(YapPlugin):
    def __init__(self, yap):
        self.yap = yap

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
        os.system("git svn init %s" % url)
	os.system("git svn fetch -r %s:HEAD" % flags.get('-r', '1'))
        self.yap.cmd_repo("svn", url)
        os.system("git config yap.svn.enabled 1")

    def _push_svn(self):
	print "Verifying branch is up-to-date"
	self.yap.cmd_fetch("svn")
	ref = self._get_svn_ref()
	rev = get_output("git rev-parse %s" % ref)
	assert rev
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

    def _get_svn_ref(self):
	fetch = get_output("git config svn-remote.svn.fetch")
	if not fetch:
	    raise YapError("No svn remote configured")
	ref = fetch[0].split(':')[1]
	return ref

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
		os.system("git svn fetch")
		return
	self.yap._call_base("cmd_fetch", *args, **flags)

    def cmd_push(self, *args, **flags):
	if self._enabled():
	    if args and args[0] == 'svn':
		self._push_svn()
		return
	self.yap._call_base("cmd_push", *args, **flags)

    @short_help("change options for the svn plugin")
    def cmd_svn(self, subcmd):
	"enable"

	if subcmd not in ["enable"]:
	    raise TypeError

	if "svn" not in [x[0] for x in self.yap._list_remotes()]:
	    raise YapError("The svn plugin requires a remote named 'svn'")

        os.system("git config yap.svn.enabled 1")
