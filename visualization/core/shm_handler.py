import ctypes
import subprocess
import threading
import time
import numpy as np
from config import MAP_SIZE, TARGET_PROCESS_NAME

# libc SHM functions
libc = ctypes.CDLL("libc.so.6")
shmat = libc.shmat
shmat.restype = ctypes.c_void_p

# Global state
accumulated_map = np.zeros(MAP_SIZE, dtype=np.uint8)
map_lock = threading.Lock()
coverage_shm_ptr = None
dist_shm_ptr = None

def get_afl_shm_ptr(target_name=TARGET_PROCESS_NAME, shm_name="AFL_SHM_ID"):
    """
    Finds the shared memory ID from the environment variables of a running process.
    """
    try:
        pid_list = subprocess.check_output(["pidof", target_name]).decode().split()
        for pid in pid_list:
            with open(f"/proc/{pid}/environ", "rb") as f:
                env = f.read().split(b'\0')
                for e in env:
                    if shm_name.encode() in e:
                        shm_id = int(e.split(b"=")[1])
                        ptr = shmat(shm_id, None, 0)
                        return ptr if ptr != -1 else None
    except Exception as e:
        # Silently fail if process or SHM not found
        pass
    return None

def shm_collector_thread():
    """
    Background thread to periodically collect coverage from SHM.
    """
    global accumulated_map, coverage_shm_ptr
    
    while True:
        if not coverage_shm_ptr:
            coverage_shm_ptr = get_afl_shm_ptr(TARGET_PROCESS_NAME, "AFL_SHM_ID")
        else:
            try:
                raw_bytes = ctypes.string_at(coverage_shm_ptr, MAP_SIZE)
                current_map = np.frombuffer(raw_bytes, dtype=np.uint8)
                with map_lock:
                    np.maximum(accumulated_map, current_map, out=accumulated_map)
            except Exception:
                coverage_shm_ptr = None # Reset if read fails
        time.sleep(0.001)

def start_collector():
    collector_thread = threading.Thread(target=shm_collector_thread, daemon=True)
    collector_thread.start()
    return collector_thread
