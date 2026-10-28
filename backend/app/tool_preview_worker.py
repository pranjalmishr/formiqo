"""Small bounded native preview worker, separate from the request process."""
import sys
from pathlib import Path
if sys.platform.startswith('linux'):
 import resource
 resource.setrlimit(resource.RLIMIT_AS,(1024*1024**2,1024*1024**2))
 resource.setrlimit(resource.RLIMIT_CPU,(15,15))
 resource.setrlimit(resource.RLIMIT_FSIZE,(10*1024**2,10*1024**2))
try:
 from .document_tools import thumbnail
 thumbnail(Path(sys.argv[1]),sys.argv[2],Path(sys.argv[3]),int(sys.argv[4]))
except Exception:
 sys.exit(2)
