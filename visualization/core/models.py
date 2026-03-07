import ctypes
from config import MAX_TARGETS, MAX_SEED_SIZE

class DistanceEntry(ctypes.Structure):
    _pack_ = 1
    _fields_ = [
        ("target_id", ctypes.c_uint32),
        ("min_distance", ctypes.c_uint32),
        ("last_bb_id", ctypes.c_uint32),
        ("seed_len", ctypes.c_uint32),
        ("is_active", ctypes.c_uint32),
        ("seed_content", ctypes.c_uint8 * MAX_SEED_SIZE),
    ]

class SharedDistKVStore(ctypes.Structure):
    _fields_ = [("entries", DistanceEntry * MAX_TARGETS)]
