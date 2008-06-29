import sys
import os
import getopt

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
    def cmd_clone(self, url, directory=""):
        # XXX: implement in terms of init + remote add + fetch
        os.system("git clone '%s' %s" % (url, directory))

    def cmd_init(self):
        os.system("git init")

    def cmd_add(self, file):
        if not os.access(file, os.R_OK):
            raise YapError("No such file: %s" % file)
        x = get_output("git ls-files '%s'" % file)
        if x != []:
            raise YapError("File '%s' already in repository" % file)
        os.system("git update-index --add '%s'" % file)
        self.cmd_status()

    def cmd_stage(self, file):
        if not os.access(file, os.R_OK):
            raise YapError("No such file: %s" % file)
        os.system("git update-index --add '%s'" % file)
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
        files = get_output("git ls-files -m")
        for f in files:
            print "\t%s" % f
        if not files:
            print "\t(none)"

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
            except (TypeError, getopt.GetoptError), e:
                if debug:
                    raise e
                print "%s %s %s" % (sys.argv[0], command, meth.__doc__)
            except YapError, e:
                print >> sys.stderr, e
                sys.exit(1)
        except AttributeError, e:
            if debug:
                raise e
            self.cmd_usage()
            sys.exit(2)
