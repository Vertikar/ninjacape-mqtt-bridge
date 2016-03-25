#!/usr/bin/python
"""
 - reads data from serial port and publishes on MQTT client
 - writes data to serial port from MQTT subscriptions

 https://github.com/perrin7/ninjacape-mqtt-bridge
 perrin7
"""

import json
import threading
import time
import logging
try:
    import Queue
except ImportError:
    # python 3
    import queue as Queue

import serial
import paho.mqtt.client as mqtt

TTY = '/dev/ttyO1'  # '/dev/ttyAMA0' for RPi
output = []


def on_connect(client, userdata, rc):
    logging.info('Connected to MQTT broker with result code %s', rc)
    client.subscribe("ninjaCape/output/#")


def on_disconnect(client, userdata, rc):
    logging.debug('Disconnected with result code %s', rc)


def on_publish(client, userdata, mid):
    logging.debug("Published message %d", mid)


def on_subscribe(client, userdata, mid, granted_qos):
    logging.debug("Subscribed %d with QoS %s", mid, granted_qos)


def on_message_output(client, userdata, msg):
    logging.debug("Received message for output %s on topic %s with QoS %s", msg.payload, msg.topic, msg.qos)
    output.append(msg)


def on_message(client, userdata, msg):
    # unmatched topic
    logging.debug("Received message %s on topic %s with QoS %s", msg.payload, msg.topic, msg.qos)


def on_log(client, userdata, level, buf):
    logging.debug("MQTT %s", buf)


def mqtt_to_json(msg):
    # JSON message in ninjaCape form -- ninjaCape/output/device/gid
    topics = msg.topic.split('/')
    return '{"DEVICE": [{"G":"%s","V":0,"D":%s,"DA":"%s"}]}' % (topics[3], topics[2], msg.payload)


def serial_read_and_publish(ser, client, queue):
    ser.reset_input_buffer()

    while True:
        line = ser.readline()  # this is blocking
        logging.debug("Line to decode: %s", line.strip())
        json_data = json.loads(line)
        logging.debug("JSON decoded: %s", json_data)
        if 'DEVICE' in json_data:
            key = 'DEVICE'
        elif 'ACK' in json_data:
            key = 'ACK'
        try:
            device = str(json_data[key][0]['D'])
            gid = str(json_data[key][0]['G'])
            data = str(json_data[key][0]['DA'])
            result, mid = client.publish("ninjaCape/input/%s/%s" % (device, gid), data)
            try:
                queue.put_nowait((key, mid))
            except Queue.Full:
                logging.warning("Message queue full")
        except KeyError:
            # should be one of: ERROR, PLUGIN, UNPLUG
            logging.warning("Received unexpected data from serial device: %s", line)


############ MAIN PROGRAM START
def main(broker, port):
    try:
        logging.debug("Connecting to serial device %s", TTY)
        ser = serial.Serial(TTY, 9600, timeout=None)
    except:
        logging.error("Failed to connect to serial device")
        raise RuntimeError

    try:
        queue = Queue.Queue()

        client = mqtt.Client()
        client.on_connect = on_connect
        client.on_disconnect = on_disconnect
        client.on_publish = on_publish
        client.on_subscribe = on_subscribe
        client.on_log = on_log
        client.on_message = on_message
        client.message_callback_add("ninjaCape/output/#", on_message_output)

        client.connect(broker, port, 60)
        client.loop_start()

        serial_thread = threading.Thread(target=serial_read_and_publish, args=(ser, client, queue))
        serial_thread.daemon = True
        serial_thread.start()

        while True:  # main thread
            if len(output) > 0:
                ser.write(mqtt_to_json(output.pop()))
                try:
                    data_type, mid = queue.get_nowait()
                    logging.debug("Received %s %s from output thread", data_type, mid)
                    if data_type == 'ACK':
                        continue
                except Queue.Empty:
                    # give the serial buffer time to flush
                    while ser.out_waiting:
                        time.sleep(0.05)
    finally:
        logging.info("Shutting down and cleaning up")
        ser.close()
        client.loop_stop()
        client.disconnect()


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='Serial to MQTT bridge for Ninjablock cape')
    parser.add_argument('-b', '--broker', default="127.0.0.1", help='MQTT broker host (default: %(default)s)')
    parser.add_argument('-p', '--port', default=1883, type=int, help='MQTT broker port (default: %(default)s)')
    parser.add_argument("-l",
                        "--log",
                        dest="loglevel",
                        choices=['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'],
                        default='INFO',
                        help="Set the logging level")
    args = parser.parse_args()
    logging.basicConfig(level=args.loglevel,
                        format='%(asctime)s %(levelname)-8s %(message)s',
                        datefmt='%Y-%m-%d %H:%M:%S')

    main(broker=args.broker, port=args.port)
