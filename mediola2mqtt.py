#!/usr/bin/env python
# (c) 2021 Andreas Böhler
# License: Apache 2.0


import paho.mqtt.client as mqtt
import socket
import json
import yaml
import os
import sys
import requests

if os.path.exists('/data/options.json'):
    print('Running in hass.io add-on mode')
    fp = open('/data/options.json', 'r')
    config = json.load(fp)
    fp.close()
elif os.path.exists('/config/mediola2mqtt.yaml'):
    print('Running in legacy add-on mode')
    fp = open('/config/mediola2mqtt.yaml', 'r')
    config = yaml.safe_load(fp)
    fp.close()
elif os.path.exists('mediola2mqtt.yaml'):
    print('Running in local mode')
    fp = open('mediola2mqtt.yaml', 'r')
    config = yaml.safe_load(fp)
    fp.close()
else:
    print('Configuration file not found, exiting.')
    sys.exit(1)

# Define MQTT event callbacks
def on_connect(client, userdata, flags, rc):
    connect_statuses = {
        0: "Connected",
        1: "incorrect protocol version",
        2: "invalid client ID",
        3: "server unavailable",
        4: "bad username or password",
        5: "not authorised"
    }
    if rc != 0:
        print("MQTT: " + connect_statuses.get(rc, "Unknown error"))
    else:
        setup_discovery()

def on_disconnect(client, userdata, rc):
    if rc != 0:
        print("Unexpected disconnection")
    else:
        print("Disconnected")

def on_message(client, obj, msg):
    print("Msg: " + msg.topic + " " + str(msg.qos) + " " + str(msg.payload))
    # Here we should send a HTTP request to Mediola to open the blind
    dtype, adr = msg.topic.split("_")
    dtype = dtype[dtype.rfind("/")+1:]
    adr = adr[:adr.find("/")]
    for ii in range(0, len(config['blinds'])):
        if dtype == config['blinds'][ii]['type'] and adr == config['blinds'][ii]['adr']:
            if msg.payload == b'open':
                if dtype == 'RT':
                    data = "20" + adr
                elif dtype == 'ER':
                    data = format(int(adr), "02x") + "01"
                else:
                    return
            elif msg.payload == b'close':
                if dtype == 'RT':
                    data = "40" + adr
                elif dtype == 'ER':
                    data = format(int(adr), "02x") + "00"
                else:
                    return
            elif msg.payload == b'stop':
                if dtype == 'RT':
                    data = "10" + adr
                elif dtype == 'ER':
                    data = format(int(adr), "02x") + "02"
                else:
                    return
            else:
                print("Wrong command")
                return
            payload = {
              "XC_FNC" : "SendSC",
              "type" : dtype,
              "data" : data
            }
            if 'password' in config['mediola'] and config['mediola']['password'] != '':
                payload['XC_PASS'] = config['mediola']['password']
            url = 'http://' + config['mediola']['host'] + '/command'
            response = requests.get(url, params=payload, headers={'Connection':'close'})

def on_publish(client, obj, mid):
    print("Pub: " + str(mid))

def on_subscribe(client, obj, mid, granted_qos):
    print("Subscribed: " + str(mid) + " " + str(granted_qos))

def on_log(client, obj, level, string):
    print(string)

def setup_discovery():
    if 'buttons' in config:
        # Buttons are configured as MQTT device triggers
        for ii in range(0, len(config['buttons'])):
            identifier = config['buttons'][ii]['type'] + '_' + config['buttons'][ii]['adr']
            deviceid = "mediola_buttons_" + config['mediola']['host'].replace(".", "")
            dtopic = config['mqtt']['discovery_prefix'] + '/device_automation/' + \
                     identifier + '/config'
            topic = config['mqtt']['topic'] + '/buttons/' + identifier
            name = "Mediola Button"
            if 'name' in config['buttons'][ii]['type']:
                name = config['buttons'][ii]['name']

            payload = {
              "automation_type" : "trigger",
              "topic" : topic,
              "type" : "button_short_press",
              "subtype" : "button_1",
              "device" : {
                "identifiers" : deviceid,
                "manufacturer" : "Mediola",
                "name" : "Mediola Button",
              },
            }
            payload = json.dumps(payload)
            mqttc.publish(dtopic, payload=payload, retain=True)

    if 'blinds' in config:
        for ii in range(0, len(config['blinds'])):
            identifier = config['blinds'][ii]['type'] + '_' + config['blinds'][ii]['adr']
            deviceid = "mediola_blinds_" + config['mediola']['host'].replace(".", "")
            dtopic = config['mqtt']['discovery_prefix'] + '/cover/' + \
                     identifier + '/config'
            topic = config['mqtt']['topic'] + '/blinds/' + identifier
            name = "Mediola Blind"
            if 'name' in config['blinds'][ii]:
                name = config['blinds'][ii]['name']

            payload = {
              "command_topic" : topic + "/set",
              "payload_open" : "open",
              "payload_close" : "close",
              "payload_stop" : "stop",
              "optimistic" : True,
              "device_class" : "blind",
              "unique_id" : identifier,
              "name" : name,
              "device" : {
                "identifiers" : deviceid,
                "manufacturer" : "Mediola",
                "name" : "Mediola Blind",
              },
            }
            if config['blinds'][ii]['type'] == 'ER':
                payload["state_topic"] = topic + "/state"
            payload = json.dumps(payload)
            mqttc.subscribe(topic + "/set")
            mqttc.publish(dtopic, payload=payload, retain=True)

def handle_button(packet_type, address, state):
    retain = False
    topic = False
    payload = False

    for ii in range(0, len(config['buttons'])):
        if packet_type == config['buttons'][ii]['type']:
            if address == config['buttons'][ii]['adr'].lower():
                identifier = config['buttons'][ii]['type'] + '_' + config['buttons'][ii]['adr']
                topic = config['mqtt']['topic'] + '/buttons/' + identifier
                payload = state
    return topic, payload, retain


def handle_blind(packet_type, address, state):
    retain = True
    topic = False
    payload = False

    for ii in range(0, len(config['blinds'])):
        if packet_type == 'ER' and packet_type == config['blinds'][ii]['type']:
            if address == config['blinds'][ii]['adr'].lower():
                identifier = config['blinds'][ii]['type'] + '_' + config['blinds'][ii]['adr']
                topic = config['mqtt']['topic'] + '/blinds/' + identifier + '/state'
                payload = 'unknown'
                if state == '01' or state == '0e':
                    payload = 'open'
                elif state == '02' or state == '0f':
                    payload = 'closed'
                elif state == '08' or state == '0a':
                    payload = 'opening'
                elif state == '09' or state == '0b':
                    payload = 'closing'
                elif state == '0d' or state == '05':
                    payload = 'stopped'
    return topic, payload, retain

def handle_packet_v4(data):
    try:
        data_dict = json.loads(data)
    except:
        return False

    packet_type = data_dict['type']
    topic, payload, retain = handle_button(packet_type,
                             data_dict['data'][0:-2].lower(),
                             data_dict['data'][-2:].lower())
    if not topic:
        topic, payload, retain = handle_blind(packet_type,
                         format(int(data_dict['data'][0:2].lower(), 16), '02d'),
                         data_dict['data'][-2:].lower())

    if topic and payload:
        mqttc.publish(topic, payload=payload, retain=retain)
        return True
    else:
        return False

def handle_packet_v6(data):
    try:
        data_dict = json.loads(data)
    except:
        return False

    packet_type = data_dict['type']
    address = data_dict['adr'].lower()
    state = data_dict['state'].lower()
    topic, payload, retain = handle_button(packet_type, address, state)
    if not topic:
        topic, payload, retain = handle_blind(packet_type,
                         format(int(address, 16), '02d'),
                         state)

    if topic and payload:
        mqttc.publish(topic, payload=payload, retain=retain)
        return True
    else:
        return False

# Setup MQTT connection
mqttc = mqtt.Client()

mqttc.on_connect = on_connect
mqttc.on_subscribe = on_subscribe
mqttc.on_disconnect = on_disconnect
mqttc.on_message = on_message

if config['mqtt']['debug']:
    print("Debugging messages enabled")
    mqttc.on_log = on_log    
    mqttc.on_publish = on_publish

if config['mqtt']['username'] and config['mqtt']['password']:
    mqttc.username_pw_set(config['mqtt']['username'], config['mqtt']['password'])
try:
    mqttc.connect(config['mqtt']['host'], config['mqtt']['port'], 60)
except:
    print('Error connecting to MQTT, will now quit.')
    sys.exit(1)
mqttc.loop_start()

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.bind(('',config['mediola']['udp_port']))

# Set up discovery structure

while True:
    valid = False
    data, addr = sock.recvfrom(1024)
    if config['mqtt']['debug']:
        print('Received message: %s' % data)
        mqttc.publish(config['mqtt']['topic'], payload=data, retain=False)

    # For the v4 (and probably v5) gateways, the status packet starts
    # with '{XC_EVT}', but for the v6 it starts with 'STA:'.
    if data.startswith(b'{XC_EVT}'):
        data = data.replace(b'{XC_EVT}', b'')
        if not handle_packet_v4(data):
            if config['mqtt']['debug']:
                print('Error handling v4 packet: %s' % data)
    elif data.startswith(b'STA:'):
        data = data.replace(b'STA:', b'')
        if not handle_packet_v6(data):
            if config['mqtt']['debug']:
                print('Error handling v6 packet: %s' % data)
