from collections import namedtuple
from time import sleep
from time import time
import tables
import numpy as np

class HDF5Frame(tables.IsDescription):
    timestamp = tables.UInt64Col() # Microseconds
    sentinel_start = tables.UInt8Col()
    sender_timestamp = tables.UInt32Col()
    sequence = tables.UInt16Col()
    id = tables.UInt16Col()
    rtr = tables.BoolCol()
    length = tables.UInt8Col()
    data = tables.UInt8Col(shape=(8,))
    sentinel_end = tables.UInt8Col()

CANFrame = namedtuple('CANFrame', [field for field in HDF5Frame.columns
                                   if field != 'timestamp'])
_H5_LOG_TABLE = "CANFrames"

class HDF5Source(object):
    def __init__(self, filename, ratelimit=False, timestamps=False, loop=False):
        self.logfile = tables.openFile(filename, 'r')
        self.log = self.logfile.root._f_getChild(_H5_LOG_TABLE)
        self.timestamps = timestamps
        self.rate_limit = ratelimit
        self.loop = loop

    def __del__(self):
        self.logfile.close()
    
    def __iter__(self):
        while True:
            last_returned = float('inf')
            last_timestamp = float('inf')
            for row in self.log.iterrows():
                if self.rate_limit:
                    inter_frame_delay = (row['sender_timestamp'] -
                                         last_timestamp)
                    delay_required = (inter_frame_delay/1e3 -
                                      (time() - last_returned))
                    if delay_required > 0:
                        sleep(delay_required)

                    last_returned = time()
                    last_timestamp = row['sender_timestamp']
                # Truncate data if necessary
                kwargs = dict((field, row[field])
                              for field in HDF5Frame.columns
                              if field not in ('data', 'timestamp'))
                frame = CANFrame(data=row['data'][:row['length']], **kwargs)
                if self.timestamps:
                    yield row['timestamp'], frame
                else:
                    yield frame
            if not self.loop:
                break


class HDF5Sink(object):
    def __init__(self, filename):
        self.logfile = tables.openFile(filename, "w")
        filters = tables.Filters(complevel=9, complib='zlib')
        self.log = self.logfile.createTable(self.logfile.root, _H5_LOG_TABLE,
                HDF5Frame, "CAN Frames from Arduino", filters=filters)
        self.writes_per_flush = 1024
        self.writes_since_flush = 0
        self.start_ts = int(time() * 1e6)
        return

    def __del__(self):
        self.logfile.close()

    def writeFrame(self, frame):
        timestamp = int(time() * 1e6) - self.start_ts
        h5frame = self.log.row
        h5frame['timestamp'] = timestamp
        h5frame['sender_timestamp'] = frame.sender_timestamp
        h5frame['sentinel_start'] = frame.sentinel_start
        h5frame['sequence'] = frame.sequence
        h5frame['id'] = frame.id
        h5frame['rtr'] = frame.rtr
        h5frame['length'] = frame.length
        h5frame['sentinel_end'] = frame.sentinel_end

        # Pad data to 8 bytes
        data = np.zeros((8,), dtype=np.uint8)
        data[:frame.length] = frame.data
        h5frame['data'] = data

        h5frame.append()
        self.writes_since_flush += 1
        if self.writes_since_flush >= self.writes_per_flush:
            self.writes_since_flush = 0
            self.log.flush()
        return
