"""The legacy logger must accept Linux serial paths in both output filenames."""
import contextlib
import csv
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from reference.HEADFIXED_PYTHON import ArduinoLogger
from reference.generate_schedule import generate_habituation_schedule


class ReferenceLoggerTests(unittest.TestCase):
    def test_habituation_start_saves_both_csvs_and_preserves_serial_port(self):
        for port in ('/dev/ttyACM0', '/dev/serial/by-id/usb-Arduino_Uno', 'COM3', r'\\.\COM12'):
            with self.subTest(port=port), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                schedule = root / 'habituation.csv'
                headers, rows = generate_habituation_schedule()
                with schedule.open('w', newline='') as file:
                    writer = csv.writer(file)
                    writer.writerow(headers)
                    writer.writerows(rows)
                connection = MagicMock()
                connection.is_open = True
                logger = ArduinoLogger('NPY195_2', port, 115200, root / 'logs', schedule)
                with patch('reference.HEADFIXED_PYTHON.serial.Serial', return_value=connection) as serial, \
                        patch('reference.HEADFIXED_PYTHON.time.sleep'), \
                        contextlib.redirect_stdout(io.StringIO()):
                    try:
                        self.assertTrue(logger.connect())
                        logger.send_command('2')
                        self.assertEqual(logger.active_mode, '2')
                        self.assertEqual(logger.status, 'RUNNING')
                    finally:
                        logger._close()
                serial.assert_called_once_with(port, 115200, timeout=1)
                files = list((root / 'logs').iterdir())
                self.assertEqual(len(files), 2)
                self.assertTrue(all(file.is_file() for file in files))
                for file in files:
                    with file.open(newline='') as stream:
                        header = next(csv.reader(stream))
                    self.assertEqual(header, headers if 'habituation_executed' in file.name else
                                     ['PC_Timestamp', 'Arduino_ms', 'Event', 'Value'])
                self.assertEqual(connection.write.call_args_list[-1].args[0], b'2')

    def test_conditioning_executed_file_also_accepts_linux_port(self):
        with tempfile.TemporaryDirectory() as directory, contextlib.redirect_stdout(io.StringIO()):
            root = Path(directory)
            logger = ArduinoLogger('NPY195_2', '/dev/ttyACM0', 115200, root)
            try:
                logger._open_executed_csv('1')
            finally:
                logger._close()
            file = next(root.iterdir())
            self.assertEqual(file.parent, root)
            with file.open(newline='') as stream:
                self.assertEqual(next(csv.reader(stream)), ['Trial', 'CS_Type', 'ITI_Duration_S'])
