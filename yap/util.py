import yap
import os

def get_output(cmd, strip=True):
    fd = os.popen(cmd)
    output = fd.readlines()
    rc = fd.close()
    if strip:
        output = [x.strip() for x in output]
    return output

def yield_output(cmd):
    fd = os.popen(cmd)
    for l in fd.xreadlines():
        yield l.strip()
    return

def run_command(cmd):
    rc = os.system("%s > /dev/null 2>&1" % cmd)
    rc >>= 8
    return rc

def run_safely(cmd):
    rc = run_command(cmd)
    if rc:
	raise yap.ShellError(cmd, rc)

def takes_options(options):
    def decorator(func):
        func.options = options
        return func
    return decorator

def short_help(help_msg):
    def decorator(func):
        func.short_help = help_msg
        return func
    return decorator

def long_help(help_msg):
    def decorator(func):
        func.long_help = help_msg
        return func
    return decorator
