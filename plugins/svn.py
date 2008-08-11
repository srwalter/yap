
from yap.yap import YapCore, YapError
from yap.util import get_output, takes_options, run_command, run_safely, short_help

import os
import tempfile
import glob
import pickle

class RepoBlob(object):
    def __init__(self, keys):
	self.keys = keys

	self.uuid = None
	self.branches = None
	self.tags = None
	self.metadata = {}

    def add_metadata(self, branch):
	assert branch not in self.metadata
	gitdir = get_output("git rev-parse --git-dir")
	assert gitdir
	revmap = os.path.join(gitdir[0], "svn", "svn", branch, ".rev_map*")
	revmap = glob.glob(revmap)
	if not revmap:
	    return
	uuid = revmap[0].split('.')[-1]
	if self.uuid is None:
	    self.uuid = uuid
	assert self.uuid == uuid
	rev = get_output("git rev-parse refs/remotes/svn/%s" % branch)
	data = file(revmap[0]).read()
	self.metadata[branch] = rev[0], data

class SvnPlugin(YapCore):
    "Allow yap to interoperate with Subversion repositories"
    def _get_root(self, url):
        root = get_output("svn info %s 2>/dev/null | gawk '/Repository Root:/{print $3}'" % url)
        if not root:
            raise YapError("Not an SVN repo: %s" % url)
        return root[0]

    def _configure_repo(self, url, fetch=None):
        root = self._get_root(url)
        os.system("git config svn-remote.svn.url %s" % root)
	if fetch is None:
	    trunk = url.replace(root, '').strip('/')
	else:
	    trunk = fetch.split(':')[0]
	os.system("git config svn-remote.svn.fetch %s:refs/remotes/svn/trunk"
		% trunk)

        branches = trunk.replace('trunk', 'branches')
	if branches != trunk:
	    os.system("git config svn-remote.svn.branches %s/*:refs/remotes/svn/*" % branches)
        tags = trunk.replace('trunk', 'tags')
	if tags != trunk:
	    os.system("git config svn-remote.svn.tags %s/*:refs/tags/*" % tags)
        self.cmd_repo("svn", url)
        os.system("git config yap.svn.enabled 1")

    def _create_tagged_blob(self):
	keys = dict()
	for i in get_output("git config --list | grep ^svn-remote.svn"):
	    k, v = i.split('=')
	    keys[k] = v
	blob = RepoBlob(keys)
	for b in get_output("git for-each-ref --format='%(refname)' 'refs/remotes/svn/*'"):
	    b = b.replace('refs/remotes/svn/', '')
	    blob.add_metadata(b)

	fd_w, fd_r = os.popen2("git hash-object -w --stdin")
	pickle.dump(blob, fd_w)
	fd_w.close()
	hash = fd_r.readline().strip()
	run_safely("git tag -f yap-svn %s" % hash)

    def _cleanup_branches(self):
	for b in get_output("git for-each-ref --format='%(refname)' 'refs/remotes/svn/*@*'"):
	    head = b.replace('refs/remotes/svn/', '')
	    path = os.path.join(".git", "svn", "svn", head)
	    files = os.listdir(path)
	    for f in files:
		os.unlink(os.path.join(path, f))
	    os.rmdir(path)

	    ref = get_output("git rev-parse %s" % b)
	    if ref:
		run_safely("git update-ref -d %s %s" % (b, ref[0]))

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

        self.cmd_init()
        run_command("git config svn-remote.svn.noMetadata 1")
        self._configure_repo(url)
	os.system("git svn fetch -r %s:HEAD" % flags.get('-r', '1'))

	self._cleanup_branches()
	self._create_tagged_blob()

    def _push_svn(self, branch, **flags):
        if '-d' in flags:
            raise YapError("Deleting svn branches not supported")
	print "Verifying branch is up-to-date"
        run_safely("git svn fetch svn")

        branch = branch.replace('refs/heads/', '')
	rev = get_output("git rev-parse --verify refs/remotes/svn/%s" % branch)

        # Create the branch if requested
        if not rev:
            if '-c' not in flags:
                raise YapError("No matching branch on the repo.  Use -c to create a new branch there.")
            src  = get_output("git svn info | gawk '/URL:/{print $2}'")[0]
            brev = get_output("git svn info | gawk '/Revision:/{print $2}'")[0]
            root = get_output("git config svn-remote.svn.url")[0]
            branch_path = get_output("git config svn-remote.svn.branches")[0].split(':')[0]
            branch_path = branch_path.rstrip('/*')
            dst = '/'.join((root, branch_path, branch))

            # Create the branch in svn
            run_safely("svn cp -r%s %s %s -m 'create branch %s'"
                    % (brev, src, dst, branch))
            run_safely("git svn fetch svn")
            rev = get_output("git rev-parse refs/remotes/svn/%s 2>/dev/null" % branch)
            base = get_output("git svn find-rev r%s" % brev)

            # Apply our commits to the new branch
            try:
                fd, tmpfile = tempfile.mkstemp("yap")
                os.close(fd)
                print base[0]
                os.system("git format-patch -k --stdout '%s' > %s"
                        % (base[0], tmpfile))
                start = get_output("git rev-parse HEAD")
                self.cmd_point("refs/remotes/svn/%s"
                        % branch, **{'-f': True})

                stat = os.stat(tmpfile)
                size = stat[6]
                if size > 0:
                    rc = run_command("git am -3 %s" % tmpfile)
                    if (rc):
                        self.cmd_point(start[0], **{'-f': True})
                        raise YapError("Failed to port changes to new svn branch")
            finally:
                os.unlink(tmpfile)

	base = get_output("git merge-base HEAD %s" % rev[0])
	if base[0] != rev[0]:
	    raise YapError("Branch not up-to-date.  Update first.")
	current = get_output("git symbolic-ref HEAD")
	if not current:
	    raise YapError("Not on a branch!")
	current = current[0].replace('refs/heads/', '')
	self._confirm_push(current, branch, "svn")
	if run_command("git update-index --refresh"):
	    raise YapError("Can't push with uncommitted changes")

	master = get_output("git rev-parse --verify refs/heads/master 2>/dev/null")
	os.system("git svn dcommit")
	run_safely("git svn rebase")
	if not master:
	    master = get_output("git rev-parse --verify refs/heads/master 2>/dev/null")
	    if master:
		run_safely("git update-ref -d refs/heads/master %s" % master[0])
    
    def _fetch_svn(self):
	os.system("git svn fetch svn")
	self._create_tagged_blob()
	self._cleanup_branches()

    def _enabled(self):
	enabled = get_output("git config yap.svn.enabled")
	return bool(enabled)

    def _applicable(self, args):
	if not self._enabled():
	    return False

	if args and args[0] == 'svn':
	    return True

	if not args:
	    current = get_output("git symbolic-ref HEAD")
	    if not current:
		raise YapError("Not on a branch!")

	    current = current[0].replace('refs/heads/', '')
	    remote, merge = self._get_tracking(current)
	    if remote == "svn":
		return True
	
	return False

    # Ensure users don't accidentally kill our "svn" repo
    def cmd_repo(self, *args, **flags):
	if self._enabled():
	    if '-d' in flags and args and args[0] == "svn":
		raise YapError("Refusing to delete special svn repository")
	super(SvnPlugin, self).cmd_repo(*args, **flags)

    @takes_options("r:")
    def cmd_clone(self, *args, **flags):
	handled = True
	if not args:
	    handled = False
	if (handled and not args[0].startswith("http")
	 	    and not args[0].startswith("svn")):
	    handled = False
	if handled and run_command("svn info %s" % args[0]):
	    handled = False

	if handled:
            self._clone_svn(*args, **flags)
	else:
            super(SvnPlugin, self).cmd_clone(*args, **flags)

	if self._enabled():
	    # nothing to do
	    return

	run_safely("git fetch origin --tags")
	hash = get_output("git rev-parse --verify refs/tags/yap-svn 2>/dev/null")
	if not hash:
	    return

	fd = os.popen("git cat-file blob %s" % hash[0])
	blob = pickle.load(fd)
	for k, v in blob.keys.items():
	    run_safely("git config %s %s" % (k, v))

        self.cmd_repo("svn", blob.keys['svn-remote.svn.url'])
        os.system("git config yap.svn.enabled 1")
	run_safely("git fetch origin 'refs/remotes/svn/*:refs/remotes/svn/*'")

	for b in blob.metadata.keys():
	    branch = os.path.join(".git", "svn", "svn", b)
	    os.makedirs(branch)
	    fd = file(os.path.join(branch, ".rev_map.%s" % blob.uuid), "w")

	    rev, metadata = blob.metadata[b]
	    fd.write(metadata)
	    run_command("git update-ref refs/remotes/svn/%s %s" % (b, rev))

    def cmd_fetch(self, *args, **flags):
	if self._applicable(args):
	    self._fetch_svn()
	    return

	super(SvnPlugin, self).cmd_fetch(*args, **flags)

    def cmd_push(self, *args, **flags):
	if self._applicable(args):
	    if len (args) >= 2:
		merge = args[1]
	    else:
                current = get_output("git symbolic-ref HEAD")
                if not current:
                    raise YapError("Not on a branch!")

                current = current[0].replace('refs/heads/', '')
                remote, merge = self._get_tracking(current)
		if remote != "svn":
		    raise YapError("Need a branch name")
	    self._push_svn(merge, **flags)
	    return
	super(SvnPlugin, self).cmd_push(*args, **flags)

    @short_help("change options for the svn plugin")
    def cmd_svn(self, subcmd):
	"enable"

	if subcmd not in ["enable"]:
	    raise TypeError

	if "svn" in [x[0] for x in self._list_remotes()]:
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
