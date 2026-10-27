"""Set process limits in a standalone launcher; never use preexec_fn in Django threads."""
import os,resource,sys
resource.setrlimit(resource.RLIMIT_CPU,(12,12))
resource.setrlimit(resource.RLIMIT_FSIZE,(16*1024*1024,16*1024*1024))
resource.setrlimit(resource.RLIMIT_NOFILE,(256,256))
if sys.platform.startswith('linux'):resource.setrlimit(resource.RLIMIT_AS,(1024*1024*1024,1024*1024*1024))
os.execv(sys.argv[1],sys.argv[1:])
