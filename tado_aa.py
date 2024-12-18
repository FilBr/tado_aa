#
# tado_aa.py (Tado Auto-Assist for Geofencing and Open Window Detection)
# Created by Adrian Slabu <adrianslabu@icloud.com> on 11.02.2021
# Edits by Filippo Barba <filippo.barba@protonmail.com> on 18.12.2024
#

import sys
import os
import time
import threading
import traceback

from datetime import datetime
from dotenv import load_dotenv
from PyTado.interface import Tado

load_dotenv()
# Settings
# --------------------------------------------------
USERNAME = os.getenv("TADO_USERNAME")  # tado username
PASSWORD = os.getenv("TADO_PASSWORD")  # tado password
CHECKING_INTERVAL = 30.0  # checking interval (in seconds)
ERROR_INTERVAL = 30.0  # retrying interval (in seconds), in case of an error
MIN_TEMP = 5  # minimum allowed temperature, applicable only if ENABLE_TEMP_LIMIT is "TRUE"
MAX_TEMP = 25  # maximum allowed temperature, applicable only if ENABLE_TEMP_LIMIT is "TRUE"
MAX_INTERNAL_TEMP = 26.0
ENABLE_TEMP_LIMIT = True  # activate min and max temp limit with "True" or disable it with "False"
SAVE_LOGS = True  # enable log saving with "True" or disable it with "False"
RESCHEDULE_TIMER = 15 * 60  # Timer to reset schedule of manually controlled areas
LOGFILE_NAME = "logfile.log"  # log file location (if you are using backslashes please add "r" before quotation mark like so: r"\tado_aa\logfile.log")
LOGFILE_PATH = os.getenv("LOGFILE_PATH")
RETENTION_LOGFILE_DAYS = 7
# --------------------------------------------------

def main():

    global last_message
    global date_last_message
    global active_reschedules

    # Keep track of messages for log rotation
    last_message = ""
    date_last_message = datetime.now().day

    # Dictionary to keep track of active reschedules and avoid creating too many threads
    active_reschedules = dict()

    login()
    home_status()


def login():

    global t

    try:
        t = Tado(USERNAME, PASSWORD, None, False)

        if last_message.find("Connection Error") != -1:
            printm("Connection established, everything looks good now, continuing..\n")

    except KeyboardInterrupt:
        printm("Interrupted by user.")
        sys.exit(0)

    except Exception as e:
        if str(e).find("access_token") != -1:
            printm("Login error, check the username / password !")
            sys.exit(0)
        else:
            printm(
                traceback.format_exc()
                + "\nConnection Error, retrying in "
                + str(ERROR_INTERVAL)
                + " sec.."
            )
            time.sleep(ERROR_INTERVAL)
            login()


def home_status():

    global devices_home

    try:
        home_state = t.get_home_state()["presence"]
        devices_home = []

        for device in t.get_mobile_devices():
            if device["settings"]["geoTrackingEnabled"] == True:
                if device["location"] != None:
                    if device["location"]["atHome"] == True:
                        devices_home.append(device["name"])

        if (
            last_message.find("Connection Error") != -1
            or last_message.find("Waiting for the device location") != -1
        ):
            printm(
                "Successfully got the location, everything looks good now, continuing..\n"
            )

        if len(devices_home) > 0 and home_state == "HOME":
            if len(devices_home) == 1:
                printm(
                    "Your home is in HOME Mode, the device "
                    + devices_home[0]
                    + " is at home."
                )
            else:
                devices = ""
                for i in range(len(devices_home)):
                    if i != len(devices_home) - 1:
                        devices += devices_home[i] + ", "
                    else:
                        devices += devices_home[i]
                printm(
                    "Your home is in HOME Mode, the devices "
                    + devices
                    + " are at home."
                )
        elif len(devices_home) == 0 and home_state == "AWAY":
            printm("Your home is in AWAY Mode and are no devices at home.")
        elif len(devices_home) == 0 and home_state == "HOME":
            printm("Your home is in HOME Mode but are no devices at home.")
            printm("Activating AWAY mode.")
            t.set_away()
            printm("Done!")
        elif len(devices_home) > 0 and home_state == "AWAY":
            if len(devices_home) == 1:
                printm(
                    "Your home is in AWAY Mode but the device "
                    + devices_home[0]
                    + " is at home."
                )
            else:
                devices = ""
                for i in range(len(devices_home)):
                    if i != len(devices_home) - 1:
                        devices += devices_home[i] + ", "
                    else:
                        devices += devices_home[i]
                printm(
                    "Your home is in AWAY Mode but the devices "
                    + devices
                    + " are at home."
                )

            printm("Activating HOME mode.")
            t.set_home()
            printm("Done!")

        devices_home.clear()
        printm("Waiting for a change in devices location or for an open window..")
        printm(
            "Temp Limit is {0}, min Temp({1}) and max Temp({2})".format(
                "ON" if (ENABLE_TEMP_LIMIT) else "OFF", MIN_TEMP, MAX_TEMP
            )
        )
        time.sleep(1)
        engine()

    except KeyboardInterrupt:
        printm("Interrupted by user.")
        sys.exit(0)

    except Exception as e:
        if str(e).find("location") != -1:
            printm(
                "I cannot get the location of one of the devices because the Geofencing is off or the user signed out from tado app.\nWaiting for the device location, until then the Geofencing Assist is NOT active.\nWaiting for an open window.."
            )
            time.sleep(1)
            engine()
        else:
            printm(
                traceback.format_exc()
                + "\nConnection Error, retrying in "
                + str(ERROR_INTERVAL)
                + " sec.."
            )
            time.sleep(ERROR_INTERVAL)
            home_status()


def reset_to_schedule(zone_id: int) -> None:
    time.sleep(RESCHEDULE_TIMER)
    t.reset_zone_overlay(zone_id)
    printm(
        f"Room {t.get_state(zone_id)['name']} resumed schedule "
        f"{t.get_state(zone_id)['setting']['power']} (set to {t.get_state(zone_id)['setting']['temperature']['value']})"
    )


def engine():
    while True:
        try:
            # Open Window Detection
            for z in t.get_zones():
                zone_id = z["roomId"]
                zone_name = z["roomName"]

                # Check internal temperature
                if t.get_state(zone_id)['sensorDataPoints']['insideTemperature']['value'] >= MAX_INTERNAL_TEMP:
                    t.reset_zone_overlay(zone_id)

                # Automatic open window mode
                if t.get_open_window_detected(zone_id)["openWindowDetected"] == True:
                    printm(
                        zone_name
                        + ": open window detected, activating the OpenWindow mode."
                    )
                    t.set_open_window(zone_id)
                    printm("Done!")
                    printm(
                        "Waiting for a change in devices location or for an open window.."
                    )

                # Resume schedule after timer
                if (
                    t.get_state(zone_id)["manualControlTermination"] is not None
                    and t.get_state(zone_id)["setting"]["power"] == "ON"
                ):
                    if zone_name not in active_reschedules or not active_reschedules[zone_name].is_alive():
                        printm(
                            f"Temperature detected {t.get_state(zone_id)['setting']['power']} (set to {t.get_state(zone_id)['setting']['temperature']['value']}) for room {zone_name} (ID: {zone_id}). "
                            f"Resuming schedule in {RESCHEDULE_TIMER//60} minutes"
                        )
                        active_reschedules[zone_name] = threading.Thread(target=reset_to_schedule, args=(zone_id,))
                        active_reschedules[zone_name].start()

                # Temp Limit
                if ENABLE_TEMP_LIMIT == True:
                    if (
                        t.get_state(zone_id)["heatingPower"]["percentage"] > 0
                        and t.get_state(zone_id)["setting"]["power"] == "ON"
                        and not t.get_state(zone_id)["setting"]["temperature"] is None
                    ):
                        set_temp = t.get_state(zone_id)["setting"]["temperature"]["value"]
                        current_temp = t.get_state(zone_id)["sensorDataPoints"][
                            "insideTemperature"
                        ]["value"]

                        if float(set_temp) > float(MAX_TEMP):
                            t.set_zone_overlay(zone_id, "MANUAL", MAX_TEMP)
                            printm(
                                "{0}: Set Temp ({1}) is higher than the desired max Temp({2}), set {0} to {2} degrees!".format(
                                    zone_name, set_temp, MAX_TEMP
                                )
                            )
                        elif float(set_temp) < float(MIN_TEMP):
                            t.set_zone_overlay(zone_id, 0, MIN_TEMP)
                            printm(
                                "{0}: Set Temp ({1}) is lower than the desired min Temp({2}), set {0} to {2} degrees!".format(
                                    zone_name, set_temp, MIN_TEMP
                                )
                            )

            # Geofencing
            home_state = t.get_home_state()["presence"]

            devices_home.clear()

            for device in t.get_mobile_devices():
                if device["settings"]["geoTrackingEnabled"] == True:
                    if device["location"] != None:
                        if device["location"]["atHome"] == True:
                            devices_home.append(device["name"])

            if (
                last_message.find("Connection Error") != -1
                or last_message.find("Waiting for the device location") != -1
            ):
                printm(
                    "Successfully got the location, everything looks good now, continuing..\n"
                )
                printm(
                    "Waiting for a change in devices location or for an open window.."
                )

            if len(devices_home) > 0 and home_state == "AWAY":
                if len(devices_home) == 1:
                    printm(devices_home[0] + " is at home, activating HOME mode.")
                else:
                    devices = ""
                    for i in range(len(devices_home)):
                        if i != len(devices_home) - 1:
                            devices += devices_home[i] + ", "
                        else:
                            devices += devices_home[i]
                    printm(devices + " are at home, activating HOME mode.")
                t.set_home()
                printm("Done!")
                printm(
                    "Waiting for a change in devices location or for an open window.."
                )

            elif len(devices_home) == 0 and home_state == "HOME":
                printm("Are no devices at home, activating AWAY mode.")
                t.set_away()
                printm("Done!")
                printm(
                    "Waiting for a change in devices location or for an open window.."
                )

            devices_home.clear()
            time.sleep(CHECKING_INTERVAL)

        except KeyboardInterrupt:
            printm("Interrupted by user.")
            sys.exit(0)

        except Exception as e:
            if str(e).find("location") != -1:
                printm(
                    "I cannot get the location of one of the devices because the Geofencing is off or the user signed out from tado app.\nWaiting for the device location, until then the Geofencing Assist is NOT active.\nWaiting for an open window.."
                )
                time.sleep(CHECKING_INTERVAL)
            else:
                printm(
                    traceback.format_exc()
                    + "\nConnection Error, retrying in "
                    + str(ERROR_INTERVAL)
                    + " sec.."
                )
                time.sleep(ERROR_INTERVAL)


def printm(message):
    global last_message
    global date_last_message

    if message != last_message:
        sys.stdout.write(
            datetime.now().strftime("%d-%m-%Y %H:%M:%S") + " # " + message + "\n"
        )

        if SAVE_LOGS == True:
            try:
                with open(os.path.join(LOGFILE_PATH, LOGFILE_NAME), "a") as log:
                    log.write(
                        datetime.now().strftime("%d-%m-%Y %H:%M:%S")
                        + " # "
                        + message
                        + "\n"
                    )
                    log.close()
            except Exception as e:
                sys.stdout.write(
                    datetime.now().strftime("%d-%m-%Y %H:%M:%S") + " # " + str(e) + "\n"
                )

            # Check the number of lines in the log file
            if datetime.now().day != date_last_message:
                rotate_log()

            date_last_message = datetime.now().day
        last_message = message


def rotate_log():
    # Create a new log file with a timestamp
    timestamp = datetime.now().strftime("%Y-%m-%d")
    new_logfile = LOGFILE_NAME.replace(".log", f"_{timestamp}.log")

    # Close the current log file and rename it
    os.rename(os.path.join(LOGFILE_PATH, LOGFILE_NAME), os.path.join(LOGFILE_PATH, new_logfile))

    # Open a new log file
    with open(os.path.join(LOGFILE_PATH, LOGFILE_NAME), "w"):
        pass

    while len([f for f in os.listdir(LOGFILE_PATH) if "logfile" in f]) > 7:
        logfiles = [f for f in os.listdir(LOGFILE_PATH) if "logfile" in f]
        if len(logfiles) > RETENTION_LOGFILE_DAYS:
            oldest_log_time = None
            oldest_log_file = None
            for f in logfiles:
                file_date = os.path.getmtime(os.path.join(LOGFILE_PATH, f))
                if oldest_log_time is None or file_date < oldest_log_time:
                    oldest_log_time = file_date
                    oldest_log_file = f

            os.remove(os.path.join(LOGFILE_PATH, oldest_log_file))


if __name__ == "__main__":
    main()
