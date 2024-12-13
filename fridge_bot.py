import paho.mqtt.client as mqtt
from telegram import Update
import telegram.ext
from telegram.ext import Updater, CommandHandler, CallbackContext, Filters, ConversationHandler, MessageHandler
import threading
import sqlite3
import cv2
import numpy as np
from datetime import datetime, timedelta
import os
import queue
import logging
import time
import tflite_runtime.interpreter as tflite

# Initialize logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# Define states
WAITING_FOR_CONFIRMATION = 1

# Replace 'YOUR_BOT_TOKEN' with your Bot's API token
token = "6861384489:AAGkAi0FrgeWBtpe19JaQ6CMR_jwHIqTkXc"
update_queue = queue.Queue()
updater = telegram.ext.Updater(token, use_context = True)

# Connect to the MQTT broker
def on_connect(client, userdata, flags, rc, properties=None):
    print("Connected with result code "+str(rc))
    client.subscribe("sensor/temperature")
    client.subscribe("sensor/humidity")
    client.subscribe("sensor/distance")

# Load label names from labels.txt file
def load_labels(filename):
    script_dir = os.path.dirname(os.path.abspath(__file__))
    file_path = os.path.join(script_dir, filename)
    with open(file_path, 'r') as f:
        return [line.strip() for line in f.readlines()]
        
# Global variables to store sensor data
temperature_data = None
humidity_data = None
distance_status = None
# Global variable to store the last time the distance status was True
last_distance_true_time = None

# Load label names
label_names = load_labels('labels.txt')
model_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "model.tflite")

# Load the TensorFlow Lite model
interpreter = tflite.Interpreter(model_path=model_path)
interpreter.allocate_tensors()
input_details = interpreter.get_input_details()
output_details = interpreter.get_output_details()

# Dictionary mapping vegetables to their estimated shelf life in days
vegetable_shelf_life = {
    "Bitter_Gourd": 2,
    "Bottle_Gourd": 2,
    "Brinjal": 2,
    "Broccoli": 2,
    "Cabbage": 2,
    "Capsicum": 1,
    "Carrot": 2,
    "Cauliflower": 2,
    "Cucumber": 2,
    "Papaya": 2,
    "Potato": 2,
    "Pumpkin": 2,
    "Radish": 2,
    "Tomato": 2
}
   
def initialize_database():
    # Connect to SQL DB
    conn = sqlite3.connect('expiry_dates.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS expiry_dates
                 (user_id INTEGER, vegetable TEXT, expiry_date TEXT, expire_in_3days BOOLEAN DEFAULT 0,expire_in_1day BOOLEAN DEFAULT 0)''')
    conn.commit()
    conn.close()

# Background task to check expiry dates periodically and send notifications
def check_expiry_dates():
    while True:
        conn = sqlite3.connect('expiry_dates.db')
        c = conn.cursor()
        c.execute("SELECT user_id, vegetable, expiry_date, expire_in_3days, expire_in_1day FROM expiry_dates")
        rows = c.fetchall()

        today = datetime.now()
        for row in rows:
            user_id, vegetable, expiry_date_str, expire_in_3days, expire_in_1day = row
            expiry_date = datetime.strptime(expiry_date_str, "%d %b %Y")

            # Delete row if today's date is more than expiry date
            if today > expiry_date:
                updater.bot.send_message(chat_id=user_id, text=f"Your {vegetable} has expired!")
                c.execute("DELETE FROM expiry_dates WHERE user_id = ? AND vegetable = ?", (user_id, vegetable))
                conn.commit()

            # Send notification if expiry date <= 3 days and notification has not been sent yet
            elif expiry_date - today <= timedelta(days=3) and not expire_in_3days:
                updater.bot.send_message(chat_id=user_id, text=f"Your {vegetable} is expiring in 3 days!")
                # Update the database to indicate notification sent
                c.execute("UPDATE expiry_dates SET expire_in_3days = 1 WHERE user_id = ? AND vegetable = ?", (user_id, vegetable))
                conn.commit()

            elif expiry_date - today <= timedelta(days=1) and not expire_in_1day:
                # Send notification for expiry in 1 day
                updater.bot.send_message(chat_id=user_id, text=f"Your {vegetable} is expiring in 1 day!")
                # Update the database to indicate notification sent
                c.execute("UPDATE expiry_dates SET expire_in_1day = 1 WHERE user_id = ? AND vegetable = ?", (user_id, vegetable))
                conn.commit()

        conn.close()
        # Refresh every hour, lower value for testing purposes
        time.sleep(5)

# Calculate expiry dates
def calculate_expiry_date(vegetable):
    # Get the shelf life of the vegetable
    shelf_life = vegetable_shelf_life.get(vegetable, None)
    if shelf_life is not None:
        # Add shelf life days to today's date
        exp_date = (datetime.now() + timedelta(days=shelf_life)).strftime("%d %b %Y")
        return exp_date
    else:
        return "Unknown"


#  ML and capture image
def start_ai(update: Update, context: CallbackContext) -> None:
    # Initialize the webcam
    cap = cv2.VideoCapture(0)
    
    update.message.reply_text(f"AI started, start capturing your vegetables!")

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        # Display the current frame
        cv2.imshow('Webcam', frame)

        # Wait for key press
        key = cv2.waitKey(1)
        
        # Terminate script if 'q' is pressed
        if key & 0xFF == ord('q'):
            update.message.reply_text(f"AI stopped running. Use /capture to start it again!")
            break
            
        # Capture image if spacebar is pressed
        elif key == ord(' '):
            # Preprocess the captured frame
            resized_frame = cv2.resize(frame, (input_details[0]['shape'][2], input_details[0]['shape'][1]))
            input_data = np.expand_dims(resized_frame, axis=0)
            input_data = (input_data.astype(np.float32) / 255.0)

            # Perform inference
            interpreter.set_tensor(input_details[0]['index'], input_data)
            interpreter.invoke()
            output_data = interpreter.get_tensor(output_details[0]['index'])

            # Get the predicted class index
            predicted_class_index = np.argmax(output_data)
            
            # Get the predicted label name
            predicted_label = label_names[predicted_class_index]

            # Print the predicted class index and label name
            print("Predicted Class Index:", predicted_class_index)
            print("Predicted Label Name:", predicted_label)
            
            # Save the captured image
            image_path = "captured_image.jpg"
            cv2.imwrite(image_path, frame)
            
            # Get today's date and time
            today = datetime.now()
            
            # Calculate expiry date and store in DB
            exp_date = calculate_expiry_date(predicted_label)
            
            # Send the captured image along with the predicted class index and label name
            context.bot.send_photo(chat_id=update.effective_chat.id, photo=open(image_path, 'rb'), caption=f"Vegetable captured: {predicted_label}. \nExpiry date: {exp_date}")
            
            # Store variables in context.user_data for later use
            context.user_data['predicted_label'] = predicted_label
            context.user_data['exp_date'] = exp_date
            
            # Ask user for confirmation
            confirm_keyboard = [[telegram.KeyboardButton("Yes"), telegram.KeyboardButton("No")]]
            reply_markup = telegram.ReplyKeyboardMarkup(confirm_keyboard, one_time_keyboard=True)
            update.message.reply_text("Confirm vegetable captured?", reply_markup=reply_markup)
            
            # Set a handler for the user's response
            return WAITING_FOR_CONFIRMATION
            break
            
    # Release resources
    cap.release()
    cv2.destroyAllWindows()

# Handle user's response for confirmation
def handle_confirmation(update: Update, context: CallbackContext) -> int:
    # Handle the user's response
    user_response = update.message.text
    if user_response.lower() == "yes":
        # If the user replied "yes", send a message
        context.bot.send_message(chat_id=update.effective_chat.id, text="I will remind you when it is expiring!")
        
        # Retrieve variables from context.user_data
        predicted_label = context.user_data['predicted_label']
        exp_date = context.user_data['exp_date']
        
        # Insert into DB
        conn = sqlite3.connect('expiry_dates.db')
        c = conn.cursor()
        c.execute("INSERT INTO expiry_dates (user_id, vegetable, expiry_date) VALUES (?, ?, ?)",(update.effective_chat.id, predicted_label, exp_date))
        conn.commit()
        conn.close()
        
    elif user_response.lower() == "no":
        # If the user replied "no"
        update.message.reply_text("Capture your image again")
    else:
        # If the user's response is not recognized, prompt again
        update.message.reply_text("Please reply with 'Yes' or 'No'.")
        return WAITING_FOR_CONFIRMATION

    # Remove the custom keyboard
    update.message.reply_text("Thanks for your response!", reply_markup=telegram.ReplyKeyboardRemove())

    return ConversationHandler.END

# Handle /start command
def start(update: Update, context: CallbackContext) -> int:
    update.message.reply_text("I am your fridge bot!\nUse /capture to start capturing your vegetables")

# Define a function to send temperature data to Telegram
def send_temperature(update: Update, context: CallbackContext) -> None:
    global temperature_data
    if temperature_data is not None:
        update.message.reply_text(f"Current temperature: {temperature_data}")
    else:
        update.message.reply_text("Temperature data not available.")# Define a function to send temperature data to Telegram
        
def send_humidity(update: Update, context: CallbackContext) -> None:
    global humidity_data
    if humidity_data is not None:
        update.message.reply_text(f"Current humidity: {humidity_data}")
    else:
        update.message.reply_text("Humidity data not available.")
        
def send_distance_status(update: Update, context: CallbackContext) -> None:
    global distance_status
    if distance_status is not None:
        update.message.reply_text(f"Door open: {distance_status}")
    else:
        update.message.reply_text("Door data not available.")
        
def on_message(client, userdata, message):
    global temperature_data,humidity_data,distance_status # Declare the global variable
    print(f"Received message on topic: {message.topic}")
    if message.topic == "sensor/temperature": # Assuming this is the topic for temperature data
        temperature_data = message.payload.decode() # Decode and store the temperature data
        print(f"Temperature data: {temperature_data}")
    elif message.topic == "sensor/humidity": # Assuming this is the topic for temperature data
        humidity_data = message.payload.decode() # Decode and store the temperature data
        print(f"Humidity data: {humidity_data}")
    else:
      distance_status = message.payload.decode()
      print(f"Door data: {distance_status}")
            

def main() -> None:
    initialize_database()
    updater = Updater(token)
    
    dispatcher = updater.dispatcher
    

    # Register command handlers
    dispatcher.add_handler(CommandHandler("start", start))
    dispatcher.add_handler(CommandHandler("temp", send_temperature))
    dispatcher.add_handler(CommandHandler("hum", send_humidity))
    dispatcher.add_handler(CommandHandler("dist", send_distance_status))

    # Set up conversation handler
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("capture", start_ai)],
        states={
            WAITING_FOR_CONFIRMATION: [MessageHandler(Filters.text & ~Filters.command, handle_confirmation)],
        },
        fallbacks=[],
    )
    
    dispatcher.add_handler(conv_handler)
    

    threading.Thread(target=check_expiry_dates).start()
    
    mqtt_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    mqtt_client.connect("192.168.47.112", 1883)
    mqtt_client.on_connect = on_connect
    mqtt_client.on_message = on_message
    

    # Start MQTT client loop
    mqtt_client.loop_start()

    # Start the Bot
    updater.start_polling()


    # Run the bot until you press Ctrl-C or the process receives SIGINT,
    # SIGTERM or SIGABRT. This should be used most of the time, since
    # start_polling() is non-blocking and will stop the bot gracefully.
    updater.idle()

if __name__ == '__main__':
    main()