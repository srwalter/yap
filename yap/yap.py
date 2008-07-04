import sys
import os
import getopt
import pickle
import tempfile

def get_output(cmd):
    fd = os.popen(cmd)
    output = fd.readlines()
    rc = fd.close()
    return [x.strip() for x in output]

def run_command(cmd):
    rc = os.system("%s > /dev/null 2>&1" % cmd)
    rc >>= 8
    return rc

class YapError(Exception):
    def __init__(self, msg):
        self.msg = msg

    def __str__(self):
        return self.msg

def takes_options(options):
    def decorator(func):
        func.options = options
        return func
    return decorator

class Yap(object):
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
        return files

    def _get_unstaged_files(self):
        files = self._get_new_files()
        files += get_output("git ls-files -m")
        return files

    def _delete_branch(self, branch, force):
        current = get_output("git symbolic-ref HEAD")[0]
        current = current.replace('refs/heads/', '')
        if branch == current:
            raise YapError("Can't delete current branch")

        ref = get_output("git rev-parse 'refs/heads/%s'" % branch)
        if not ref:
            raise YapError("No such branch: %s" % branch)
        os.system("git update-ref -d 'refs/heads/%s' '%s'" % (branch, ref[0]))

        if not force:
            name = get_output("git name-rev --name-only '%s'" % ref[0])[0]
            if name == 'undefined':
                os.system("git update-ref 'refs/heads/%s' '%s'" % (branch, ref[0]))
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
            os.system("git rm --cached '%s'" % file)
        self._remove_new_file(file)

    def _stage_one(self, file):
        self._assert_file_exists(file)
        os.system("git update-index --add '%s'" % file)

    def _unstage_one(self, file):
        self._assert_file_exists(file)
        if run_command("git rev-parse HEAD"):
            os.system("git update-index --force-remove '%s'" % file)
        else:
            os.system("git diff-index -p HEAD '%s' | git apply -R --cached" % file)

    def _revert_one(self, file):
        self._assert_file_exists(file)
        os.system("git checkout-index -f '%s'" % file)

    def cmd_clone(self, url, directory=""):
        "<url> [directory]"
        # XXX: implement in terms of init + remote add + fetch
        os.system("git clone '%s' %s" % (url, directory))

    def cmd_init(self):
        os.system("git init")

    def cmd_add(self, *files):
        "<file>..."
        if not files:
            raise TypeError
        
        for f in files:
            self._add_one(f)
        self.cmd_status()

    def cmd_rm(self, *files):
        "<file>..."
        if not files:
            raise TypeError
        
        for f in files:
            self._rm_one(f)
        self.cmd_status()

    def cmd_stage(self, *files):
        "<file>..."
        if not files:
            raise TypeError
        
        for f in files:
            self._stage_one(f)
        self.cmd_status()

    def cmd_unstage(self, *files):
        "<file>..."
        if not files:
            raise TypeError
        
        for f in files:
            self._unstage_one(f)
        self.cmd_status()

    def cmd_status(self):
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
        prefix = get_output("git rev-parse --show-prefix")
        files = self._get_unstaged_files()
        for f in files:
            if prefix:
                f = os.path.join(prefix[0], f)
            print "\t%s" % f
        if not files:
            print "\t(none)"

    @takes_options("a")
    def cmd_revert(self, *files, **flags):
        "(-a | <file>)"
        if '-a' in flags:
            os.system("git checkout-index -f -a")
            return

        if not files:
            raise TypeError

        for f in files:
            self._revert_one(f)
        self.cmd_status()

    @takes_options("ad")
    def cmd_commit(self, **flags):
        if '-a' in flags and '-d' in flags:
            raise YapError("Conflicting flags: -a and -d")

        if '-d' not in flags and self._get_unstaged_files():
            if '-a' not in flags and self._get_staged_files():
                raise YapError("Staged and unstaged changes present.  Specify what to commit")
            os.system("git diff-files -p | git apply --cached 2>/dev/null")
            for f in self._get_new_files():
                self._stage_one(f)

        if not self._get_staged_files():
            raise YapError("No changes to commit")

        tree = get_output("git write-tree")[0]

        parent = get_output("git rev-parse HEAD 2> /dev/null")[0]

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
        if os.system("%s '%s'" % (editor, tmpfile)) != 0:
            raise YapError("Editing commit message failed")
        if parent != 'HEAD':
            commit = get_output("git commit-tree '%s' -p '%s' < '%s'" % (tree, parent, tmpfile))
        else:
            commit = get_output("git commit-tree '%s' < '%s'" % (tree, tmpfile))
        if not commit:
            raise YapError("Commit failed; no log message?")
        os.unlink(tmpfile)
        os.system("git update-ref HEAD '%s'" % commit[0])
        self.cmd_status()

    def cmd_uncommit(self):
        tree = get_output("git rev-parse HEAD^")
        os.system("git update-ref -m uncommit HEAD '%s'" % tree[0])
        self.cmd_status()

    def cmd_version(self):
        print "Yap version 0.1"

    @takes_options("r:")
    def cmd_log(self, *paths, **flags):
        "[-r <rev>] <path>..."
        rev = flags.get('-r', 'HEAD')
        paths = ' '.join(paths)
        os.system("git log --name-status '%s' -- %s" % (rev, paths))

    @takes_options("ud")
    def cmd_diff(self, **flags):
        "[ -u | -d ]"
        if '-u' in flags and '-d' in flags:
            raise YapError("Conflicting flags: -u and -d")

        pager = self._get_pager_cmd()

        os.system("git update-index -q --refresh")
        if '-u' in flags:
            os.system("git diff-files -p | %s" % pager)
        elif '-d' in flags:
            os.system("git diff-index --cached -p HEAD | %s" % pager)
        else:
            os.system("git diff-index -p HEAD | %s" % pager)

    @takes_options("fd:")
    def cmd_branch(self, branch=None, **flags):
        "[ [-f] -d <branch> | <branch> ]"
        force = '-f' in flags
        if '-d' in flags:
            self._delete_branch(flags['-d'], force)
            self.cmd_branch()
            return

        if branch is not None:
            ref = get_output("git rev-parse HEAD")
            if not ref:
                raise YapError("No branch point yet.  Make a commit")
            os.system("git update-ref 'refs/heads/%s' '%s'" % (branch, ref[0]))

        current = get_output("git symbolic-ref HEAD")[0]
        branches = get_output("git for-each-ref --format='%(refname)' 'refs/heads/*'")
        for b in branches:
            if b == current:
                print "* ",
            else:
                print "  ",
            b = b.replace('refs/heads/', '')
            print b

    def cmd_switch(self, branch):
        "<branch>"
        ref = get_output("git rev-parse 'refs/heads/%s'" % branch)
        if not ref:
            raise YapError("No such branch: %s" % branch)

        # XXX: support merging like git-checkout
        if self._get_unstaged_files() or self._get_staged_files():
            raise YapError("You have uncommitted changes.  Commit them first")

        os.system("git symbolic-ref HEAD refs/heads/'%s'" % branch)
        os.system("git read-tree HEAD")
        os.system("git checkout-index -f -a")
        self.cmd_branch()

    @takes_options("f")
    def cmd_point(self, where, **flags):
        "<where>"
        head = get_output("git rev-parse HEAD")
        if not head:
            raise YapError("No commit yet; nowhere to point")

        ref = get_output("git rev-parse '%s'" % where)
        if not ref:
            raise YapError("Not a valid ref: %s" % where)

        if self._get_unstaged_files() or self._get_staged_files():
            raise YapError("You have uncommitted changes.  Commit them first")

        type = get_output("git cat-file -t '%s'" % ref[0])
        if type and type[0] == "tag":
            tag = get_output("git cat-file tag '%s'" % ref[0])
            ref[0] = tag[0].split(' ')[1]

        os.system("git update-ref HEAD '%s'" % ref[0])

        if '-f' not in flags:
            name = get_output("git name-rev --name-only '%s'" % head[0])[0]
            if name == "undefined":
                os.system("git update-ref HEAD '%s'" % head[0])
                raise YapError("Pointing there will lose commits.  Use -f to force")

        os.system("git read-tree HEAD")
        os.system("git checkout-index -f -a")
        os.system("git update-index --refresh")

    def cmd_history(self, subcmd, commit):
        "amend | drop <commit>"

        if subcmd not in ("amend", "drop"):
            raise TypeError

        # XXX: ensure no rebase in progress

        if subcmd == "amend":
            # XXX: Use cmd_commit rules
            stash = get_output("git stash create")
            os.system("git reset --hard")
            if not stash:
                raise YapError("Failed to stash; no changes?")

        fd, tmpfile = tempfile.mkstemp("yap")
        os.close(fd)
        try:
            os.system("git format-patch -k --stdout '%s' > %s" % (commit, tmpfile))
            if subcmd == "amend":
                self.cmd_point(commit, **{'-f': True})
                run_command("git stash apply --index %s" % stash[0])
                # XXX: use cmd_commit instead
                os.system("git commit --amend")
                stash = get_output("git stash create")
                os.system("git reset --hard")
            else:
                self.cmd_point("%s^" % commit, **{'-f': True})

            stat = os.stat(tmpfile)
            size = stat[6]
            if size > 0:
                rc = os.system("git am -3 '%s' > /dev/null" % tmpfile)
                if (rc):
                    raise YapError("Failed to apply changes")

            if subcmd == "amend" and stash:
                run_command("git stash apply %s" % stash[0])
        finally:
            os.unlink(tmpfile)
        self.cmd_status()

    def cmd_usage(self):
        print >> sys.stderr, "usage: %s <command>" % sys.argv[0]
        print >> sys.stderr, "  valid commands: init add rm stage unstage status revert commit uncommit log diff branch switch point history version"

    def main(self, args):
        if len(args) < 1:
            self.cmd_usage()
            sys.exit(2)

        command = args[0]
        args = args[1:]

        debug = os.getenv('YAP_DEBUG')

        try:
            meth = self.__getattribute__("cmd_"+command)
            try:
                if "options" in meth.__dict__:
                    flags, args = getopt.getopt(args, meth.options)
                    flags = dict(flags)
                else:
                    flags = dict()

                meth(*args, **flags)
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
