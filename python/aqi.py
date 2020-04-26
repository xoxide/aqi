#!/usr/bin/python -u
# coding=utf-8
# "DATASHEET": http://cl.ly/ekot
# https://gist.github.com/kadamski/92653913a53baf9dd1a8
from __future__ import print_function
import serial, struct, sys, time, json, subprocess, ConfigParser, threading

DEBUG = 0
CMD_MODE = 2
CMD_QUERY_DATA = 4
CMD_DEVICE_ID = 5
CMD_SLEEP = 6
CMD_FIRMWARE = 7
CMD_WORKING_PERIOD = 8
MODE_ACTIVE = 0
MODE_QUERY = 1
PERIOD_CONTINUOUS = 0

config = ConfigParser.ConfigParser()
config.read('config/config.txt')

JSON_FILE = config.get('SETTINGS', 'JSON_FILE')
MQTT_HOST = config.get('SETTINGS', 'MQTT_HOST')
MQTT_TOPIC = config.get('SETTINGS', 'MQTT_TOPIC')
MQTT_USER = config.get('SETTINGS', 'MQTT_USER')
MQTT_PASSWORD = config.get('SETTINGS', 'MQTT_PASSWORD')
MQTT_PORT = config.get('SETTINGS', 'MQTT_PORT')
MQTT_CAFILE = config.get('SETTINGS', 'MQTT_CAFILE')
MQTT_CRT = config.get('SETTINGS', 'MQTT_CRT')
MQTT_KEY = config.get('SETTINGS', 'MQTT_KEY')


ser = serial.Serial()
ser.port = "/dev/ttyUSB0"
ser.baudrate = 9600
#ser.timeout = None          #block read
ser.timeout = 1            #non-block read
#ser.timeout = 2              #timeout block read
ser.xonxoff = False     #disable software flow control
ser.rtscts = False     #disable hardware (RTS/CTS) flow control
ser.dsrdtr = False       #disable hardware (DSR/DTR) flow control
ser.writeTimeout = 2     #timeout for write

ser.open()
ser.flushInput()

byte, data = 0, ""


def dump(d, prefix=''):
    print(prefix + ' '.join(x.encode('hex') for x in d))


def construct_command(cmd, data=[]):
    assert len(data) <= 12
    data += [0, ] * (12 - len(data))
    checksum = (sum(data) + cmd - 2) % 256
    ret = "\xaa\xb4" + chr(cmd)
    ret += ''.join(chr(x) for x in data)
    ret += "\xff\xff" + chr(checksum) + "\xab"

    if DEBUG:
        dump(ret, '> ')
    return ret


def process_data(d):
    r = struct.unpack('<HHxxBB', d[2:])
    pm25 = r[0] / 10.0
    pm10 = r[1] / 10.0
    checksum = sum(ord(v) for v in d[2:8]) % 256
    return [pm25, pm10]
    # print("PM 2.5: {} μg/m^3  PM 10: {} μg/m^3 CRC={}".format(pm25, pm10, "OK" if (checksum==r[2] and r[3]==0xab) else "NOK"))


def process_version(d):
    r = struct.unpack('<BBBHBB', d[3:])
    checksum = sum(ord(v) for v in d[2:8]) % 256
    print("Y: {}, M: {}, D: {}, ID: {}, CRC={}".format(r[0], r[1], r[2], hex(r[3]),
                                                       "OK" if (checksum == r[4] and r[5] == 0xab) else "NOK"))

def read_response():
  return ser.read(max(1, min(8, ser.in_waiting)))
    # byte = 0
    # while byte != "\xaa":
        # byte = ser.read(size=1)

    # d = ser.read(ser.inWaiting())

    # if DEBUG:
        # dump(d, '< ')
    # return byte + d


def cmd_set_mode(mode=MODE_QUERY):
    ser.write(construct_command(CMD_MODE, [0x1, mode]))
    read_response()


def cmd_query_data():
    ser.write(construct_command(CMD_QUERY_DATA))
    d = read_response()
    values = []
    if d[1] == "\xc0":
        values = process_data(d)
    return values


def cmd_set_sleep(sleep):
    mode = 0 if sleep else 1
    ser.write(construct_command(CMD_SLEEP, [0x1, mode]))
    read_response()


def cmd_set_working_period(period):
    ser.write(construct_command(CMD_WORKING_PERIOD, [0x1, period]))
    read_response()


def cmd_firmware_ver():
    ser.write(construct_command(CMD_FIRMWARE))
    d = read_response()
    print(d)
    process_version(d)


def cmd_set_id(id):
    id_h = (id >> 8) % 256
    id_l = id % 256
    ser.write(construct_command(CMD_DEVICE_ID, [0] * 10 + [id_l, id_h]))
    read_response()


def pub_mqtt(jsonrow):
    cmd = ['mosquitto_pub', '-d', '--cafile', MQTT_CAFILE, '--cert', MQTT_CRT, '--key', MQTT_KEY, '-h', MQTT_HOST, '-t',
           MQTT_TOPIC, '-p', MQTT_PORT, '-u', MQTT_USER, '-P', MQTT_PASSWORD, '-r', '-s']

    with subprocess.Popen(cmd, shell=False, bufsize=0, stdin=subprocess.PIPE).stdin as f:
        json.dump(jsonrow, f)


def calc_aqi_pm25(pm25):
    pm1 = 0
    pm2 = 12
    pm3 = 35.4
    pm4 = 55.4
    pm5 = 150.4
    pm6 = 250.4
    pm7 = 350.4
    pm8 = 500.4

    aqi1 = 0
    aqi2 = 50
    aqi3 = 100
    aqi4 = 150
    aqi5 = 200
    aqi6 = 300
    aqi7 = 400
    aqi8 = 500

    aqipm25 = 0

    if (pm25 >= pm1) and (pm25 <= pm2):
        aqipm25 = ((aqi2 - aqi1) / (pm2 - pm1)) * (pm25 - pm1) + aqi1
    elif (pm25 >= pm2) and (pm25 <= pm3):
        aqipm25 = ((aqi3 - aqi2) / (pm3 - pm2)) * (pm25 - pm2) + aqi2
    elif (pm25 >= pm3) and (pm25 <= pm4):
        aqipm25 = ((aqi4 - aqi3) / (pm4 - pm3)) * (pm25 - pm3) + aqi3
    elif (pm25 >= pm4) and (pm25 <= pm5):
        aqipm25 = ((aqi5 - aqi4) / (pm5 - pm4)) * (pm25 - pm4) + aqi4
    elif (pm25 >= pm5) and (pm25 <= pm6):
        aqipm25 = ((aqi6 - aqi5) / (pm6 - pm5)) * (pm25 - pm5) + aqi5
    elif (pm25 >= pm6) and (pm25 <= pm7):
        aqipm25 = ((aqi7 - aqi6) / (pm7 - pm6)) * (pm25 - pm6) + aqi6
    else:
        aqipm25 = ((aqi8 - aqi7) / (pm8 - pm7)) * (pm25 - pm7) + aqi7

    return aqipm25


def calc_aqi_pm10(pm10):
    pm1 = 0
    pm2 = 54
    pm3 = 154
    pm4 = 254
    pm5 = 354
    pm6 = 424
    pm7 = 504
    pm8 = 604

    aqi1 = 0
    aqi2 = 50
    aqi3 = 100
    aqi4 = 150
    aqi5 = 200
    aqi6 = 300
    aqi7 = 400
    aqi8 = 500

    aqipm10 = 0

    if (pm10 >= pm1) and (pm10 <= pm2):
        aqipm10 = ((aqi2 - aqi1) / (pm2 - pm1)) * (pm10 - pm1) + aqi1
    elif (pm10 >= pm2) and (pm10 <= pm3):
        aqipm10 = ((aqi3 - aqi2) / (pm3 - pm2)) * (pm10 - pm2) + aqi2
    elif (pm10 >= pm3) and (pm10 <= pm4):
        aqipm10 = ((aqi4 - aqi3) / (pm4 - pm3)) * (pm10 - pm3) + aqi3
    elif (pm10 >= pm4) and (pm10 <= pm5):
        aqipm10 = ((aqi5 - aqi4) / (pm5 - pm4)) * (pm10 - pm4) + aqi4
    elif (pm10 >= pm5) and (pm10 <= pm6):
        aqipm10 = ((aqi6 - aqi5) / (pm6 - pm5)) * (pm10 - pm5) + aqi5
    elif (pm10 >= pm6) and (pm10 <= pm7):
        aqipm10 = ((aqi7 - aqi6) / (pm7 - pm6)) * (pm10 - pm6) + aqi6
    else:
        aqipm10 = ((aqi8 - aqi7) / (pm8 - pm7)) * (pm10 - pm7) + aqi7

    return aqipm10


if __name__ == "__main__":
    cmd_set_sleep(0)
    cmd_firmware_ver()
    cmd_set_working_period(PERIOD_CONTINUOUS)
    cmd_set_mode(MODE_QUERY)
    reading_event = threading.Event()
    reading_thread = threading.Thread(target=read_response, daemon=True)

    while True:
        cmd_set_sleep(0)
        for t in range(15):
            values = cmd_query_data()

            if values is not None and len(values) == 2:
                print("PM2.5: ", values[0], ", PM10: ", values[1])
                time.sleep(2)

        # open stored data
        try:
            with open(JSON_FILE) as json_data:
                data = json.load(json_data)
        except IOError as e:
            data = []

        # check if length is more than 100 and delete first element
        if len(data) > 100:
            data.pop(0)


        # append new values
        jsonrow = {'pm25': values[0], 'pm10': values[1], 'time': time.strftime("%d.%m.%Y %H:%M:%S")}
        data.append(jsonrow)

        # save it
        with open(JSON_FILE, 'w') as outfile:
            json.dump(data, outfile)

        if MQTT_HOST != '':
            pm25 = calc_aqi_pm25(values[0])
            pm10 = calc_aqi_pm10(values[1])

            jsonrow = {'pm25': pm25, 'pm10': pm10, 'time': time.strftime("%d.%m.%Y %H:%M:%S")}

            pub_mqtt(jsonrow)

        print("Going to sleep for 1 min...")
        cmd_set_sleep(1)
        time.sleep(60)
