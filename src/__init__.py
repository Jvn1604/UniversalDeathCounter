"""
DePhantom Universal Death Counter.

numpy's maths library (OpenBLAS) would otherwise start a worker thread per CPU
core and reserve memory for each: about 740 MB of commit and 23 idle threads
on a 24-thread CPU. The app's small image checks gain nothing from them. This
runs before anything imports numpy, for the app, the tests and the frozen exe.
"""

import os

os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("OMP_NUM_THREADS", "1")
