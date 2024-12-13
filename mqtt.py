# -*- coding: utf-8 -*-
import paho.mqtt.client as mqtt
import time
import random
from gpiozero import DistanceSensor
import RPi.GPIO as GPIO
import board
import adafruit_dht

# MQTT broker address and port
broker_address = "192.168.47.112"
port = 1883

# Initial the dht device, with data pin connected to:
dhtDevice = adafruit_dht.DHT11(board.D4)

ultrasonic = DistanceSensor(echo=17, trigger=27)
GPIO.setmode(GPIO.BCM)
GPIO.setwarnings(False)

prev_state = None

# Create a client instance
client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)

# Connect to the broker
client.connect(broker_address, port)

i = 0

# Publish sensor data to multiple MQTT topics
while i == 0:
  try:
      # Simulating sensor data (replace this with actual sensor readings)
      temperature = dhtDevice.temperature
      humidity = dhtDevice.humidity
      distance = ultrasonic.distance
      if distance < 0.1 and prev_state != 'close':
          print("Close")
          prev_state = 'close'
          status = False
      elif distance >= 0.1 and prev_state != 'open':
          print("Open")
          prev_state = 'open'
          status = True
  
      # Publish temperature, humidity, and distance to respective MQTT topics
      client.publish("sensor/temperature", f"{temperature}\u00b0C")
      client.publish("sensor/humidity", f"{humidity}%")
      client.publish("sensor/distance", status)
    
  except RuntimeError as error:     # Errors happen fairly often, DHT's are hard to read, just keep going
         print(error.args[0])

    # Publish interval (in seconds)
  time.sleep(2)