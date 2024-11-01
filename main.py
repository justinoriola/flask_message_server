import traceback
import time
from flask import Flask, request, jsonify
import os
from twilio.rest import Client
from dotenv import load_dotenv
import json

# Load environment variables from .env file
load_dotenv(dotenv_path='.env')

# twilio credentials and WhatsApp numbers
TWILIO_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
MY_NUMBER = 'whatsapp:' + os.getenv("MY_NUMBER")
MANAGER_NUMBERS = [MY_NUMBER, 'whatsapp:' + os.getenv("BOLANLE_NUMBER")]
TWILIO_WHATSAPP_NUMBER = os.getenv("TWILIO_WHATSAPP_NUMBER")

# Set up Flask app and Twilio client
app = Flask(__name__)
client = Client(TWILIO_SID, TWILIO_AUTH_TOKEN)

# Dictionary to track approval state for each user request
conversation_history = {}


def process_incoming_message(message_parameters):
    try:
        updates = {}  # Temporary dictionary for conversation history updates

        # unpack message_parameters
        for account_id_key, account_id_value in message_parameters.items():
            senders_number = account_id_value.get('sender_number', '')
            approval_message = account_id_value.get('approval_message', '')
            senders_name = account_id_value.get('sender_profile_name').title()
            original_replied_message_sid = account_id_value.get('original_replied_message_sid', '')

            # update manager's approval into conversation_history
            if senders_number in MANAGER_NUMBERS:
                if approval_message == 'approve':

                    # Update approval status for matching original_replied_message_sid
                    account_id_value['approval_status'] = 'approve'
                    updates[original_replied_message_sid] = account_id_value
                    return updates, original_replied_message_sid, senders_number, approval_message, senders_name

                elif approval_message == 'decline':
                    account_id_value['approval_status'] = 'decline'
                    updates[original_replied_message_sid] = account_id_value
                    return updates, original_replied_message_sid, senders_number, approval_message, senders_name

            else:
                senders_name = account_id_value.get('sender_profile_name').title()  # get sender's name
                template_message = '{{1}} is requesting for credit.'  # setup template message

                # Send WhatsApp message and retrieve new SID
                new_message_sid = send_whatsapp_message(template_message, MY_NUMBER, senders_name)
                updates[new_message_sid] = account_id_value
                return updates, new_message_sid, senders_number, approval_message, senders_name

    except RuntimeError:
        pass
    except Exception as e:
        print('error occurred within the process_incoming_message function', e)
        traceback.print_exc()  # This will print the full traceback


def process_approval(*args):
    try:
        # unpack args variables
        new_message_sid = args[1]
        senders_number = args[2]
        approval_message = args[3]
        senders_name = args[4]
        ticket_id = new_message_sid[-5:]

        # pre-check for approval
        if approval_message in ['approve', 'decline']:
            return False

        # fetch approval message
        if new_message_sid in conversation_history:
            print(f"Awaiting approval in 30(sec)...", end='', flush=True)

            # wait for approval
            counter = 30
            while counter > 0:
                # get approval status from conversation_history
                approval_status = conversation_history[new_message_sid].get('approval_status', '')

                # break if request is approved
                if approval_status == 'approve':
                    message = f'\n[Ticket ID : #{ticket_id.upper()}] Status : Approved | Requester: {senders_name}'
                    print(message)
                    send_whatsapp_message(message, senders_number)
                    del conversation_history[new_message_sid]
                    return True

                # break if request is declined
                if approval_status == 'decline':
                    message = f'\n[Ticket ID : #{ticket_id.upper()}] Status : Decline | Requester: {senders_name}'
                    print(message)
                    send_whatsapp_message(message, senders_number)
                    del conversation_history[new_message_sid]
                    break

                # reduce counter value and avoid infinite loop
                time.sleep(1)  # Adding a small delay to prevent a rapid loop
                counter -= 1

                # Move the cursor up and overwrite the line with the new counter value
                print(f"\033!", end='', flush=True)

            # Handle case where approval was not received within the timeout
            if counter == 0:
                print(f"\nApproval timed out for {new_message_sid}")
                return False

    except (KeyError, IndexError):
        pass
    except Exception as e:
        print('\nerror occurred within the process_approval function', e)
        traceback.print_exc()  # This will print the full traceback


def get_incoming_message_data(data):
    global conversation_history
    """
    :param data: this function receives incoming message and process it
    """
    try:
        # Process incoming message
        incoming_message = data.get('Body', '')
        sender_number = data.get('From', '')
        message_sid = data.get('SmsMessageSid', '')
        approval_message = incoming_message.lower()
        sender_profile_name = data.get('ProfileName', '')
        original_replied_message_sid = data.get('OriginalRepliedMessageSid', '')

        # update conversation_history with incoming conversations data
        incoming_msg_parameters = {
            message_sid: {
                'incoming_message': incoming_message,
                'sender_number': sender_number,
                'approval_message': approval_message,
                'approval_status': None,
                'sender_profile_name': sender_profile_name,
                'original_replied_message_sid': original_replied_message_sid
            }
        }

        # return incoming message data
        return incoming_msg_parameters

    except Exception as e:
        print('error occurred within the get_incoming_message_data', e)


def send_whatsapp_message(message_text, recipient, *params):
    """function to send a WhatsApp message"""
    try:
        # Format message if params are provided, otherwise use as-is
        if params:
            for i, param in enumerate(params, start=1):  # Replace placeholders with values if params are provided
                message_body = message_text.replace(f"{{{{{i}}}}}", param)
        else:
            # Regular message with no placeholders
            message_body = message_text

        message = client.messages.create(
            from_='whatsapp:' + TWILIO_WHATSAPP_NUMBER,
            body=message_body,
            to=recipient
        )
        print(f"\nMessage sent to {recipient}: {message.sid}")
        return message.sid

    except Exception as e:
        print("Failed to send message:", e)


# Route to handle incoming messages from Twilio
@app.route('/webhook', methods=['POST', 'GET'])
def webhook():
    try:
        # Access the initial POST request data
        data = request.values.to_dict()

        # get incoming message
        incoming_message_details = get_incoming_message_data(data)

        # process incoming msg function and update approval
        approval_update = process_incoming_message(incoming_message_details)

        # update conversation_history dictionary
        conversation_history.update(approval_update[0])

        # instantiate process_approval function
        process_approval(*approval_update)
        #
        return "\nWebhook received", 200

    except Exception as e:
        print("Error occurred within webhook function:", str(e))
        traceback.print_exc()  # This will print the full traceback
        return "Internal Server Error", 500


if __name__ == "__main__":
    app.run(debug=True, port=5001)

