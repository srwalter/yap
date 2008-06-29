import sys
import os
import getopt
import pickle

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

    def cmd_clone(self, url, directory=""):
        # XXX: implement in terms of init + remote add + fetch
        os.system("git clone '%s' %s" % (url, directory))

    def cmd_init(self):
        os.system("git init")

    def cmd_add(self, file):
        self._assert_file_exists(file)
        x = get_output("git ls-files '%s'" % file)
        if x != []:
            raise YapError("File '%s' already in repository" % file)
        self._add_new_file(file)
        self.cmd_status()

    def cmd_rm(self, file):
        self._assert_file_exists(file)
        if get_output("git ls-files '%s'" % file) != []:
            os.system("git rm --cached '%s'" % file)
        self._remove_new_file(file)
        self.cmd_status()

    def cmd_stage(self, file):
        self._assert_file_exists(file)
        os.system("git update-index --add '%s'" % file)
        self.cmd_status()

    def cmd_unstage(self, file):
        self._assert_file_exists(file)
        if run_command("git rev-parse HEAD"):
            os.system("git update-index --force-remove '%s'" % file)
        else:
            os.system("git diff-index HEAD '%s' | git apply -R --cached" % file)
        self.cmd_status()

    def cmd_status(self):
        branch = get_output("git symbolic-ref HEAD")[0]
        branch = branch.replace('refs/heads/', '')
        print "Current branch: %s" % branch

        print "Files with staged changes:"
        if run_command("git rev-parse HEAD"):
            files = get_output("git ls-files --cached")
        else:
            files = get_output("git diff-index --name-only HEAD")
        for f in files:
            print "\t%s" % f
        if not files:
            print "\t(none)"

        print "Files with unstages changes:"
        files = self._get_new_files()
        files += get_output("git ls-files -m")
        for f in files:
            print "\t%s" % f
        if not files:
            print "\t(none)"

    def cmd_unedit(self, file):
        self._assert_file_exists(file)
        os.system("git checkout-index -f '%s'" % file)
        self.cmd_status()

    def cmd_version(self):
        print "Yap version 0.1"

    def cmd_usage(self):
        print >> sys.stderr, "usage: %s <command>" % sys.argv[0]
        print >> sys.stderr, "  valid commands: version"

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
                if "option" in meth.__dict__:
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
