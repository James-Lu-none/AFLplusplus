#!/usr/bin/env python3
import sys
import subprocess

def main():
    if len(sys.argv) < 4:
        print("Usage: dafl_svf_slicer.py <bitcode_path> <target_location> <output_dir>", file=sys.stderr)
        sys.exit(1)
    
    cmd = ["/usr/local/bin/dafl_svf_slicer"] + sys.argv[1:]
    res = subprocess.run(cmd)
    sys.exit(res.returncode)

if __name__ == '__main__':
    main()
