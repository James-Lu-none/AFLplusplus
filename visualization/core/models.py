import ctypes
from config import MAX_TARGETS, MAX_SEED_SIZE, MAX_PATH_LEN

class DistanceEntry(ctypes.Structure):
    _pack_ = 1
    _fields_ = [
        ("target_id", ctypes.c_uint32),
        ("min_distance", ctypes.c_uint32),
        ("last_bb_id", ctypes.c_uint32),
        ("seed_len", ctypes.c_uint32),
        ("active_count", ctypes.c_uint32),
        ("seed_content", ctypes.c_uint8 * MAX_SEED_SIZE),
        ("path_len", ctypes.c_uint32),
        ("path_content", ctypes.c_uint32 * MAX_PATH_LEN),
    ]

class SharedDistKVStore(ctypes.Structure):
    _fields_ = [("entries", DistanceEntry * MAX_TARGETS)]
