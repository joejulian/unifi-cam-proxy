""""
Helper program to inject absolute wall clock time into FLV stream for recordings
"""

import argparse
import struct
import sys
import time

from flvlib3.astypes import FLVObject
from flvlib3.primitives import make_ui8
from flvlib3.tags import create_script_tag


def read_bytes(source, num_bytes):
    read_bytes = 0
    buf = b""
    while read_bytes < num_bytes:
        d_in = source.read(num_bytes - read_bytes)
        if d_in:
            read_bytes += len(d_in)
            buf += d_in
        else:
            return buf
    return buf


def write(data):
    sys.stdout.buffer.write(data)


def write_log(data):
    sys.stderr.buffer.write(f"{data}\n".encode())


def write_timestamp_trailer(is_packet, ts):
    # Keep the full 64-bit counter in Protect's 16-byte timestamp extension.
    # Encoding only its low 32 bits crashes after about 13 hours at 90 kHz.
    timebase = 90000 if is_packet else 11025
    write(struct.pack(">IIQ", timebase, 0, int(ts * 1000)))


def main(args):
    source = sys.stdin.buffer

    header = read_bytes(source, 3)

    if header != b"FLV":
        print("Not a valid FLV file")
        return
    write(header)

    # Skip rest of FLV header
    write(read_bytes(source, 1))
    flags = read_bytes(source, 1)
    if not flags:
        return
    # Enable Protect's timestamp extension without inventing an audio track.
    write(make_ui8(flags[0] | 2))
    write(read_bytes(source, 4))

    # Tag 0 previous size
    write(read_bytes(source, 4))

    last_ts = time.time()
    start = time.time()
    i = 0
    while True:
        # Packet structure from Wikipedia:
        #
        # Size of previous packet	uint32_be	0	For first packet set to NULL
        #
        # Packet Type	uint8	18	For first packet set to AMF Metadata
        # Payload Size	uint24_be	varies	Size of packet data only
        # Timestamp Lower	uint24_be	0	For first packet set to NULL
        # Timestamp Upper	uint8	0	Extension to create a uint32_be value
        # Stream ID	uint24_be	0	For first stream of same type set to NULL
        #
        # Payload Data	freeform	varies	Data as defined by packet type

        header = read_bytes(source, 12)
        if len(header) != 12:
            write(header)
            return

        # Packet type
        packet_type = header[0]

        # Get payload size to know how many bytes to read
        high, low = struct.unpack(">BH", header[1:4])
        payload_size = (high << 16) + low

        # Get timestamp to inject into clock sync tag
        low_high = header[4:8]
        combined = bytes([low_high[3]]) + low_high[:3]
        timestamp = struct.unpack(">i", combined)[0]

        now = time.time()
        if not last_ts or now - last_ts >= 5:
            last_ts = now
            # Insert a custom packet every so often for time synchronization
            data = FLVObject()
            data["streamClock"] = int(timestamp)
            data["streamClockBase"] = 0
            data["wallClock"] = now * 1000
            packet_to_inject = create_script_tag("onClockSync", data, timestamp)
            write(packet_to_inject)

            # Write 15 byte trailer
            write_timestamp_trailer(False, (now - start) * args.timestamp_modifier)

            # Write mpma tag
            # {'cs': {'cur': 1500000.0,
            #         'max': 1500000.0,
            #         'min': 32000.0},
            #  'm': {'cur': 750000.0,
            #        'max': 1500000.0,
            #        'min': 750000.0},
            #  'r': 0.0,
            #  'sp': {'cur': 1500000.0,
            #         'max': 1500000.0,
            #         'min': 150000.0},
            #  't': 750000.0}

            data = FLVObject()
            data["cs"] = FLVObject()
            data["cs"]["cur"] = 1500000
            data["cs"]["max"] = 1500000
            data["cs"]["min"] = 1500000

            data["m"] = FLVObject()
            data["m"]["cur"] = 1500000
            data["m"]["max"] = 1500000
            data["m"]["min"] = 1500000
            data["r"] = 0

            data["sp"] = FLVObject()
            data["sp"]["cur"] = 1500000
            data["sp"]["max"] = 1500000
            data["sp"]["min"] = 1500000
            data["t"] = 75000.0
            packet_to_inject = create_script_tag("onMpma", data, 0)

            write(packet_to_inject)

            # Write 15 byte trailer
            write_timestamp_trailer(False, (now - start) * args.timestamp_modifier)

            # Write rest of original packet minus previous packet size
            write(header)
            write(read_bytes(source, payload_size))
        else:
            # Write the original packet
            write(header)
            write(read_bytes(source, payload_size))

        # Write previous packet size
        write(read_bytes(source, 3))

        # Write 15 byte trailer
        write_timestamp_trailer(
            packet_type == 9, (now - start) * args.timestamp_modifier
        )

        # Write mpma tag
        i += 1


def parse_args():
    parser = argparse.ArgumentParser(description="Modify Protect FLV stream")
    parser.add_argument(
        "--timestamp-modifier",
        type=int,
        default="90",
        help="Modify the timestamp correction factor (default: 90)",
    )
    return parser.parse_args()


if __name__ == "__main__":
    main(parse_args())
