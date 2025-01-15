'''Python script to control Tado devices based on the location of the devices and the temperature of the rooms.'''

import sys
import os
import time
import threading
import traceback
from datetime import datetime
from dotenv import load_dotenv
from PyTado.interface import Tado

# Load environment variables
load_dotenv()

class TadoController:
    '''
    TadoController class to control Tado devices
    '''
    # Configuration settings
    CHECKING_INTERVAL = 30.0
    ERROR_INTERVAL = 30.0
    MIN_TEMP = 5
    MAX_TEMP = 25
    MAX_INTERNAL_TEMP = 26.0
    ENABLE_TEMP_LIMIT = True
    SAVE_LOGS = True
    RESCHEDULE_TIMER = 15 * 60
    LOGFILE_NAME = "logfile.log"
    LOGFILE_PATH = os.getenv("LOGFILE_PATH")
    RETENTION_LOGFILE_DAYS = 7

    def __init__(self, username: str, password: str):
        '''
        Initialize the TadoController class

        :param username: Tado username
        :param password: Tado password
        '''
        self.username = username
        self.password = password
        self.last_message = ""
        self.date_last_message = datetime.now().day
        self.active_reschedules = {}
        self.stop_flags = {}
        self.t: Tado | None = None
        self.devices_home = []

    def login(self):
        '''
        Login to a Tado account
        '''
        try:
            self.t = Tado(self.username, self.password, None, False)

            if "Connection Error" in self.last_message:
                self.print_message("Connection established, continuing..")

        except KeyboardInterrupt:
            self.print_message("Interrupted by user.")
            sys.exit(0)

        except Exception as e:
            if "access_token" in str(e):
                self.print_message("Login error, check credentials!")
                sys.exit(0)
            else:
                self.print_message(
                    traceback.format_exc() + "\nConnection Error, retrying in " + str(self.ERROR_INTERVAL) + " sec.."
                )
                time.sleep(self.ERROR_INTERVAL)
                self.login()

    def home_status(self):
        '''
        Check home status. If no devices are at home, activate AWAY mode.
        '''
        try:
            home_state = self.t.get_home_state()["presence"]

            if not self.devices_home:
                for device in self.t.get_mobile_devices():
                    if device["settings"]["geoTrackingEnabled"] and device["location"]["atHome"]:
                        self.devices_home.append(device["name"])

            if "Connection Error" in self.last_message:
                self.print_message("Successfully got the location, continuing..")

            if self.devices_home and home_state == "HOME":
                self.manage_home_mode(len(self.devices_home))
            elif not self.devices_home and home_state == "AWAY":
                self.print_message("No devices at home, activating AWAY mode.")
                self.t.set_away()
            elif not self.devices_home and home_state == "HOME":
                self.print_message("Activating AWAY mode.")
                self.t.set_away()
            elif self.devices_home and home_state == "AWAY":
                self.manage_home_mode(len(self.devices_home))

            self.print_message("Waiting for a change in device location..")
            self.print_message(f"Temp Limit is {'ON' if self.ENABLE_TEMP_LIMIT else 'OFF'}, min Temp({self.MIN_TEMP}), max Temp({self.MAX_TEMP})")
            time.sleep(1)
            self.engine()

        except KeyboardInterrupt:
            self.print_message("Interrupted by user.")
            sys.exit(0)

        except Exception as e:
            if "location" in str(e):
                self.print_message("Waiting for device location.")
                time.sleep(1)
            else:
                self.print_message(
                    traceback.format_exc() + "\nConnection Error, retrying in " + str(self.ERROR_INTERVAL) + " sec.."
                )
                time.sleep(self.ERROR_INTERVAL)
                self.home_status()

    def manage_home_mode(self, num_devices):
        '''
        Manage home mode. If at least one device is at home, activate HOME mode.
        '''
        if num_devices == 1:
            self.print_message(f"Home Mode activated. Device {self.devices_home[0]} is at home.")
        else:
            devices = ", ".join(self.devices_home)
            self.print_message(f"Home Mode activated. Devices {devices} are at home.")
        self.t.set_home()

    def reset_to_schedule(self, zone_id, zone_name):
        '''
        Reset the zone to the schedule. To be launched in a separate thread.
        '''
        try:
            while not self.stop_flags.get(zone_name, False):
                if time.sleep(0.1):
                    return

                remaining_time = self.RESCHEDULE_TIMER
                while remaining_time > 0 and not self.stop_flags.get(zone_name, False):
                    time.sleep(min(1, remaining_time))
                    remaining_time -= 1

                if self.stop_flags.get(zone_name, False):
                    self.print_message(f"Room {self.t.get_state(zone_id)['name']} reschedule stopped")
                    return

                self.t.reset_zone_overlay(zone_id)
                self.print_message(
                    f"Room {self.t.get_state(zone_id)['name']} resumed schedule "
                    f"{self.t.get_state(zone_id)['setting']['power']}{' (set to ' + str(self.t.get_state(zone_id)['setting']['temperature']['value']) + ')' if self.t.get_state(zone_id)['setting']['temperature'] is not None else ''}"
                )

        finally:
            if zone_name in self.active_reschedules:
                del self.active_reschedules[zone_name]
            if zone_name in self.stop_flags:
                del self.stop_flags[zone_name]

    def engine(self):
        '''
        Main engine to control the Tado devices
        '''
        while True:
            try:
                for zone in self.t.get_zones():
                    zone_id = zone["roomId"]
                    zone_name = zone["roomName"]

                    if self.t.get_open_window_detected(zone_id)["openWindowDetected"]:
                        if "activated" in self.t.get_state(zone_id)["openWindow"] and self.t.get_state(zone_id)['openWindow']['activated']:
                            self.print_message(f"{zone_name}: Open window detected, OpenWindow mode already activated.")
                            continue
                        self.print_message(f"{zone_name}: Open window detected, activating OpenWindow mode.")
                        self.t.set_open_window(zone_id)
                        self.print_message("Done!")
                        continue

                    if self.t.get_state(zone_id)['sensorDataPoints']['insideTemperature']['value'] >= self.MAX_INTERNAL_TEMP:
                        self.t.reset_zone_overlay(zone_id)

                    if self.t.get_state(zone_id)["manualControlTermination"] and self.t.get_state(zone_id)["setting"]["power"] == "ON":
                        if zone_name not in self.active_reschedules or not self.active_reschedules[zone_name].is_alive():
                            self.print_message(
                                f"Temperature detected {self.t.get_state(zone_id)['setting']['power']} (set to {self.t.get_state(zone_id)['setting']['temperature']['value']}) for room {zone_name} (ID: {zone_id}). "
                                f"Resuming schedule in {self.RESCHEDULE_TIMER//60} minutes"
                            )
                            self.active_reschedules[zone_name] = threading.Thread(target=self.reset_to_schedule, args=(zone_id, zone_name,))
                            self.stop_flags[zone_name] = False
                            self.active_reschedules[zone_name].start()

                    if self.t.get_state(zone_id)["manualControlTermination"] and self.t.get_state(zone_id)["setting"]["power"] == "OFF":
                        if zone_name in self.active_reschedules and self.active_reschedules[zone_name].is_alive():
                            self.print_message(f"Room {zone_name} heating is OFF, stopping reschedule thread")
                            self.stop_flags[zone_name] = True
                            if zone_name in self.active_reschedules:
                                self.active_reschedules[zone_name].join(timeout=self.CHECKING_INTERVAL + 1)

                    if self.ENABLE_TEMP_LIMIT:
                        if (
                            self.t.get_state(zone_id)["heatingPower"]["percentage"] > 0
                            and self.t.get_state(zone_id)["setting"]["power"] == "ON"
                            and self.t.get_state(zone_id)["setting"]["temperature"] is not None
                        ):
                            set_temp = self.t.get_state(zone_id)["setting"]["temperature"]["value"]

                            if set_temp > self.MAX_TEMP:
                                self.t.set_zone_overlay(zone_id, "MANUAL", self.MAX_TEMP)
                                self.print_message(
                                    f"{zone_name}: Set Temp ({set_temp}) is higher than the desired max Temp({self.MAX_TEMP}), set {zone_name} to {self.MAX_TEMP} degrees!"
                                )
                            elif set_temp < self.MIN_TEMP:
                                self.t.set_zone_overlay(zone_id, 0, self.MIN_TEMP)
                                self.print_message(
                                    f"{zone_name}: Set Temp ({set_temp}) is lower than the desired min Temp({self.MIN_TEMP}), set {zone_name} to {self.MIN_TEMP} degrees!"
                                )

                home_state = self.t.get_home_state()["presence"]

                self.devices_home.clear()

                if not self.devices_home:
                    for device in self.t.get_mobile_devices():
                        if device["settings"]["geoTrackingEnabled"] and device["location"]["atHome"]:
                            self.devices_home.append(device["name"])

                if "Connection Error" in self.last_message:
                    self.print_message("Successfully got the location, continuing..")
                    self.print_message("Waiting for a change in device location..")

                if self.devices_home and home_state == "AWAY":
                    self.manage_home_mode(len(self.devices_home))

                elif not self.devices_home and home_state == "HOME":
                    self.print_message("Activating AWAY mode.")
                    self.t.set_away()

                self.devices_home.clear()
                time.sleep(self.CHECKING_INTERVAL)

            except KeyboardInterrupt:
                self.print_message("Interrupted by user.")
                sys.exit(0)

            except Exception as e:
                if "location" in str(e):
                    self.print_message("Waiting for device location.")
                else:
                    self.print_message(
                        traceback.format_exc() + "\nConnection Error, retrying in " + str(self.ERROR_INTERVAL) + " sec.."
                    )
                    time.sleep(self.ERROR_INTERVAL)

    def print_message(self, message):
        '''
        Print a formatted message to the console and save it to a log file
        '''
        if message != self.last_message:
            sys.stdout.write(datetime.now().strftime("%d-%m-%Y %H:%M:%S") + " # " + message + "\n")

            if self.SAVE_LOGS:
                try:
                    with open(os.path.join(self.LOGFILE_PATH, self.LOGFILE_NAME), "a") as log:
                        log.write(datetime.now().strftime("%d-%m-%Y %H:%M:%S") + " # " + message + "\n")
                except Exception as e:
                    sys.stdout.write(datetime.now().strftime("%d-%m-%Y %H:%M:%S") + " # " + traceback.format_exc() + str(e) + "\n")

            if datetime.now().day != self.date_last_message:
                self.rotate_log()

            self.date_last_message = datetime.now().day
            self.last_message = message

    def rotate_log(self):
        '''
        Rotate the log file based on the date
        '''
        timestamp = datetime.now().strftime("%Y-%m-%d")
        new_logfile = self.LOGFILE_NAME.replace(".log", f"_{timestamp}.log")
        os.rename(os.path.join(self.LOGFILE_PATH, self.LOGFILE_NAME), os.path.join(self.LOGFILE_PATH, new_logfile))
        open(os.path.join(self.LOGFILE_PATH, self.LOGFILE_NAME), "w").close()

        while len([f for f in os.listdir(self.LOGFILE_PATH) if "logfile" in f]) > self.RETENTION_LOGFILE_DAYS:
            logfiles = [f for f in os.listdir(self.LOGFILE_PATH) if "logfile" in f]
            oldest_log_time = None
            oldest_log_file = None
            for f in logfiles:
                file_date = os.path.getmtime(os.path.join(self.LOGFILE_PATH, f))
                if oldest_log_time is None or file_date < oldest_log_time:
                    oldest_log_time = file_date
                    oldest_log_file = f

            os.remove(os.path.join(self.LOGFILE_PATH, oldest_log_file))

if __name__ == "__main__":
    controller = TadoController(username=os.getenv("TADO_USERNAME"), password=os.getenv("TADO_PASSWORD"))
    controller.login()
    controller.home_status()