"""Bounded, nonblocking USB serial transport; no hardware opened on import."""


class SerialBoard:
    def __init__(self, port, baud=115200):
        import serial
        self.serial = serial.Serial(port, baud, timeout=0, write_timeout=.5)
        self.buffer = bytearray()

    def write_line(self, line):
        data = (line + "\n").encode("ascii")
        if self.serial.write(data) != len(data):
            raise IOError("Incomplete Arduino command write")

    def read_lines(self):
        waiting = self.serial.in_waiting
        if waiting:
            self.buffer.extend(self.serial.read(min(waiting, 8192)))
        if len(self.buffer) > 16384:
            raise IOError("Arduino receive buffer overflow")
        lines = []
        while b"\n" in self.buffer:
            line, _, rest = self.buffer.partition(b"\n")
            self.buffer = bytearray(rest)
            lines.append(line.decode("ascii", errors="strict").rstrip("\r"))
        return lines

    def close(self):
        self.serial.close()
