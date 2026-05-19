import runpy, os, sys
_dir = os.path.dirname(os.path.abspath(__file__))
os.chdir(_dir)
runpy.run_path(os.path.join(_dir, "launcher.py"), run_name="__main__")
