#!/usr/bin/env python

from YeelightWifiBulbLanCtrl import *
import json
import urllib2
import math
import os
import signal
import logging
from collections import Counter
# sudo apt-get install python-dateutil
from datetime import date, datetime
from dateutil import tz
import dateutil.parser

class SmartYeelight(object):

    def __init__(self, apply_light_policy_interval = 10, device_detection_interval = 10, device_offline_delay = 10, debug = False):
        self.__yeelight_detection_thread = None
        self.__device_detection_thread = None
        self.__device_detection_thread_woker = {}
        self.__apply_light_policy_thread = None
        self.__current_geo = None
        self.__compiled_policy = []
        self.__compiled_policy_date = None
        self.__device_on_monitor = []
        self.__device_online = []
        self.__device_detection_interval = device_detection_interval
        self.__apply_light_policy_interval = apply_light_policy_interval
        self.__device_offline_delay = device_offline_delay
        self.__RUNNING = False
        # a few setups
        self.__setup_log()
        signal.signal(signal.SIGINT, self.__signal_handler)
        signal.signal(signal.SIGTERM, self.__signal_handler)
        signal.signal(signal.SIGUSR1, self.__signal_handler)

    def __setup_log(self):
        logger = logging.getLogger("SmartYeelightCtrl")
        logger.setLevel(logging.INFO)
        # create the logging file handler
        fh = logging.FileHandler("smart-yeelight-controller.log")
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        fh.setFormatter(formatter)
        # add handler to logger object
        logger.addHandler(fh)
        self.__logger = logger

    def deploy_policy(self, light_policy):
        self.__get_compiled_policy(light_policy)

    def __start_yeelight(self):
        if self.__yeelight_detection_thread is None:
            RUNNING = True
            self.__yeelight_detection_thread = Thread(target = bulbs_detection_loop)
            self.__yeelight_detection_thread.setDaemon(True)
            self.__yeelight_detection_thread.start()

    def __stop_yeelight(self):
        if self.__yeelight_detection_thread is not None:
            RUNNING = False
            self.__yeelight_detection_thread.join()
            self.__yeelight_detection_thread = None

    def __register_device_for_monitor(self, device_list = []):
        for device_ip in device_list:
            if device_ip not in self.__device_on_monitor:
                self.__device_on_monitor.append(device_ip)

    def __unregister_all_device_for_monitor(self):
        self.__stop_detect_device_worker()
        self.__device_on_monitor = []
        self.__device_online = []

    def __detect_device_loop(self):
        while self.__device_detection_thread is not None:
            for device_ip in self.__device_on_monitor:
                if device_ip in self.__device_detection_thread_woker:
                    continue
                thread = Thread(target = self.__detect_device_worker, args = (device_ip, ))
                self.__device_detection_thread_woker[device_ip] = thread
                thread.setDaemon(True)
                thread.start()
            sleep(self.__device_detection_interval)

    def __detect_device_worker(self, ip):
        retry = self.__device_offline_delay
        device_is_online = False
        while not device_is_online and retry > 0:
            retry -= 1
            device_is_online = (os.system("ping -c 1 "+ ip +" > /dev/null 2>&1") == 0)
            if device_is_online:
                if ip not in self.__device_online:
                    self.__device_online.append(ip)
                    self.__logger.info('Device gets online: %s', ip)
                break
            if retry > 0:
                self.__logger.debug('Device %s is going to be offline in %s retries.', ip, retry)
            sleep(0.2)
        if not device_is_online and ip in self.__device_online:
            self.__device_online.remove(ip)
            self.__logger.info('Device gets offline: %s', ip)
        self.__device_detection_thread_woker.pop(ip, None)

    def __start_detect_device(self):
        if self.__device_detection_thread is None:
            self.__device_detection_thread = Thread(target = self.__detect_device_loop)
            self.__device_detection_thread.setDaemon(True)
            self.__device_detection_thread.start()

    def __stop_detect_device(self):
        if self.__device_detection_thread is not None:
            thread = self.__device_detection_thread
            # set thread to None so that the loop can exit
            self.__device_detection_thread = None
            thread.join()

    def __stop_detect_device_worker(self):
        for device_ip, worker in self.__device_detection_thread_woker:
            worker.cancel()
        self.__device_detection_thread_woker = {}

    def __apply_light_policy_loop(self):
        while self.__apply_light_policy_thread is not None:
            self.__apply_light_policy()
            sleep(self.__apply_light_policy_interval)

    def __apply_light_policy(self):
        # recalculate light brightness
        calculated_light_brigtness = self.calculate_light_brightness()
        self.change_yeelight_brightness(calculated_light_brigtness)

    def __start_apply_light_policy(self):
        if self.__apply_light_policy_thread is None:
            self.__apply_light_policy_thread = Thread(target = self.__apply_light_policy_loop)
            self.__apply_light_policy_thread.setDaemon(True)
            self.__apply_light_policy_thread.start()

    def __stop_apply_light_policy(self):
        if self.__apply_light_policy_thread is not None:
            thread = self.__apply_light_policy_thread
            # set thread to None so that the loop can exit
            self.__apply_light_policy_thread = None
            thread.join()

    def __get_overlap_between_lists(self, list1, list2):
        l1_multiset = Counter(list1)
        l2_multiset = Counter(list2)
        overlap = list((l1_multiset & l2_multiset).elements())
        return overlap

    def __at_least_one_device_online(self, device_list):
        if self.__get_overlap_between_lists(device_list, self.__device_online):
            return True
        else:
            return False

    def start(self):
        self.__logger.debug("Controller started")
        self.__start_yeelight()
        self.__start_detect_device()
        self.__start_apply_light_policy()
        self.__RUNNING = True

    def stop(self):
        self.__logger.debug("Controller stopped")
        self.__RUNNING = False
        self.__stop_apply_light_policy()
        self.__stop_detect_device()
        self.__stop_detect_device_worker()
        self.__stop_yeelight()

    def is_running(self):
        return self.__RUNNING

    def __signal_handler(self, signal, frame):
        self.stop()
        os._exit(0)

    def __http_get(self, url, timeout = 3):
        try:
            r = urllib2.urlopen(url, timeout = timeout)
            return json.load(r)
        except urllib2.URLError as e:
            self.__logger.error("Error fetching %s - %s", url, e.reason)

    def __get_datetime(self, iso_time):
        if id(type) and type(iso_time) in (datetime, date):
            return iso_time
        else:
            return dateutil.parser.parse(str(iso_time))

    def __get_localtime(self, iso_time, timezone = tz.tzlocal()):
        iso_datetime = self.__get_datetime(iso_time)
        local = iso_datetime.astimezone(timezone)
        return local

    def __parse_time(self, time_string, current_time, format = '%H:%M:%S'):
        time  = datetime.strptime(time_string, format).replace(year = current_time.year, month = current_time.month, day = current_time.day, tzinfo = tz.tzlocal())
        return self.__get_localtime(time)

    def __get_diff_between_datetime(self, datetime1, datetime2 = datetime(1970,1,1)):
        td = datetime1 - datetime2
        return (td.microseconds + (td.seconds + td.days * 86400) * 10**6) / 10**6

    def __get_compiled_policy(self, light_policy, current_time = None, enforce_update = False):
        if current_time is None:
            current_time = datetime.now().replace(tzinfo = tz.tzlocal())
        if enforce_update or self.__compiled_policy_date is None or current_time.date() != self.__compiled_policy_date.date():
            self.__unregister_all_device_for_monitor()
            self.__compiled_policy = self.__compile_policy(light_policy, current_time)
            self.__compiled_policy_date = current_time
            self.__logger.info('Local policy cache updated: %s', self.__compiled_policy)
        return self.__compiled_policy

    def __compile_policy(self, light_policy, current_time):
        compiled_policy = []
        today = current_time.date()
        today_sun_time = self.get_sun_time(today)
        for bulb in light_policy:
            if 'bulb_ip' not in bulb:
                continue
            compiled_bulb_policy = { "bulb_ip" : bulb["bulb_ip"], "policies" : [] }
            if 'light_on_only_when_device_online' in bulb and bulb['light_on_only_when_device_online']:
                compiled_bulb_policy['light_on_only_when_device_online'] = bulb['light_on_only_when_device_online']
                self.__register_device_for_monitor(compiled_bulb_policy['light_on_only_when_device_online'])
            for policy in bulb['policies']:
                compiled_light_policy = {}
                # replace keywords with dynamic time
                for key in policy:
                    if isinstance(policy[key], basestring) and policy[key] in today_sun_time:
                        compiled_light_policy[key] = today_sun_time[policy[key]]
                    else:
                        compiled_light_policy[key] = policy[key]
                if 'bright_time' not in compiled_light_policy or 'dark_time' not in compiled_light_policy:
                    continue
                # 24-hour format
                if isinstance(compiled_light_policy['bright_time'], basestring):
                    compiled_light_policy['bright_time'] = self.__parse_time(compiled_light_policy['bright_time'], current_time)
                if isinstance(compiled_light_policy['dark_time'], basestring):
                    compiled_light_policy['dark_time'] =  self.__parse_time(compiled_light_policy['dark_time'], current_time)
                # we remove the obsoleted from compiled policy
                if max(compiled_light_policy['bright_time'], compiled_light_policy['dark_time']) < current_time:
                    continue
                if 'const_brightness' in compiled_light_policy:
                    compiled_light_policy['const_brightness'] = int(compiled_light_policy['const_brightness'])
                    compiled_light_policy.pop('min_brightness', None)
                    compiled_light_policy.pop('max_brightness', None)
                compiled_bulb_policy["policies"].append(compiled_light_policy)
            compiled_policy.append(compiled_bulb_policy)
        self.__logger.debug('Policy compiled: %s', compiled_policy)
        return compiled_policy

    def calculate_light_brightness(self, current_time = None, light_policy = None):
        self.__logger.debug('Calculating light brightness..')
        if current_time is None:
            current_time = datetime.now().replace(tzinfo = tz.tzlocal())
        calculated_light_brigtness = []
        compiled_policy = self.__compiled_policy
        if light_policy is not None:
            compiled_policy = self.__compile_policy(light_policy, current_time)
        if compiled_policy is None:
            self.__logger.error("No policy is found. Skip light update")
            return calculated_light_brigtness
        for bulb in compiled_policy:
            calculated_light = { "bulb_ip" : bulb["bulb_ip"] }
            if bulb["light_on_only_when_device_online"] and not self.__at_least_one_device_online(bulb["light_on_only_when_device_online"]):
                # if required devices are not online, turn off the light
                calculated_light["calculated_brightness"] = 0
            else:
                for policy in bulb['policies']:
                    brightness = self.__calculate_light_brightness(current_time, policy)
                    if brightness > -1:
                        calculated_light["calculated_brightness"] = brightness
                        calculated_light["policy_matched"] = policy
                        break
            if 'calculated_brightness' in calculated_light:
                calculated_light_brigtness.append(calculated_light)
        self.__logger.debug('Calculated light brightness: %s', calculated_light_brigtness)
        return calculated_light_brigtness

    def __calculate_light_brightness(self, current_time, light_policy = {}):
        bright_time, dark_time = light_policy['bright_time'], light_policy['dark_time']
        if current_time < min(bright_time, dark_time) or current_time > max(bright_time, dark_time):
            return -1   # return -1 when current time is not within the bright_time and dark_time range
        # if there is a constant brightness value, return immediately
        if 'const_brightness' in light_policy:
            return light_policy['const_brightness']
        min_brightness, max_brightness = 0, 100
        if 'min_brightness' in light_policy:
            min_brightness = light_policy['min_brightness']
        if 'max_brightness' in light_policy:
            max_brightness = light_policy['max_brightness']
        time_scale = abs(self.__get_diff_between_datetime(bright_time, dark_time))
        time_passed = abs(self.__get_diff_between_datetime(current_time, bright_time))
        brightness = int(math.ceil(min_brightness + float(time_passed) / float(time_scale) * float(max_brightness - min_brightness)))
        brightness += min_brightness
        return brightness

    def __get_geo(self):
        api_url = 'https://freegeoip.net/json'
        while self.__current_geo is None:
            r = self.__http_get(api_url)
            self.__logger.info('Geo Location: %s', r)
            self.__current_geo = r
        return self.__current_geo

    def get_sun_time(self, date, geo = None):
        if geo is None:
            geo = self.__get_geo()
        lat, lng = geo['latitude'], geo['longitude']
        api_url = 'http://api.sunrise-sunset.org/json?formatted=0&lat='+ str(lat) +'&lng='+ str(lng) +'&date='+ str(date)
        self.__logger.debug('Sunset/Sunset API URL: %s', api_url)
        r = self.__http_get(api_url)
        t = r['results']
        self.__logger.debug('Sunrise/Sunset (UTC) time for date '+ str(date) +': %s', t)
        t['sunrise'] = self.__get_localtime(t['sunrise'])
        t['sunset'] = self.__get_localtime(t['sunset'])
        t['civil_twilight_begin'] = self.__get_localtime(t['civil_twilight_begin'])
        t['civil_twilight_end'] = self.__get_localtime(t['civil_twilight_end'])
        self.__logger.info('Sunrise/Sunset (local) time for date '+ str(date) +': %s', t)
        return t

    def change_yeelight_brightness(self, bulb_policy = []):
        for policy in bulb_policy:
            self.__change_yeelight_brightness(policy)

    def __change_yeelight_brightness(self, bulb_policy):
        bulb_ip_list, target_bulb_brightness = bulb_policy["bulb_ip"], bulb_policy["calculated_brightness"]
        for bulb_ip in bulb_ip_list:
            if bulb_ip not in detected_bulbs:
                self.__logger.warning("Bulb %s is offline.", bulb_ip)
                continue
            bulb = detected_bulbs[bulb_ip]
            self.__logger.debug("Bulb %s is online. Bulb info: %s", bulb_ip, bulb)
            self.__logger.debug("Applying policy: %s", bulb_policy)
            bulb_id, bulb_power, bulb_bright = bulb[0], bulb[2], int(bulb[3])
            if target_bulb_brightness > 0:
                if bulb_power == 'off': # turn on light
                    self.__logger.debug("Turn on yeelight %s", bulb_ip)
                    toggle_bulb(bulb_id)
                if bulb_bright != target_bulb_brightness:
                    self.__logger.info('Set yeelight %s to brightness %s', bulb_ip, target_bulb_brightness)
                    set_bright(bulb_id, target_bulb_brightness)
            elif target_bulb_brightness == 0:
                if bulb_power == 'on': # turn off light
                    self.__logger.info("Turn yeelight %s off.", bulb_ip)
                    toggle_bulb(bulb_id)


if __name__ == "__main__":
    light_policy = [
        {
            "bulb_ip" : [ "192.168.2.31" ],
            "light_on_only_when_device_online" : [ "192.168.2.51", "192.168.2.53" ], # leave this empty if you want the policy be executed regardless if the device is online
            "policies" : [
                {
                    "bright_time" : "00:00:00",
                    "dark_time" : "02:00:00",
                    "max_brightness" : 80,
                    "min_brightness" : 1,
                },
                {
                    "bright_time" : "02:00:00",
                    "dark_time" : "sunrise",
                    "const_brightness" : 0,
                },
                {
                    "bright_time" : "sunrise",
                    "dark_time" : "civil_twilight_begin",
                    "const_brightness" : 0,
                }, 
                {
                    "bright_time" : "civil_twilight_end",
                    "dark_time" : "sunset",
                },
                {
                    "bright_time" : "sunrise",
                    "dark_time" : "sunset",
                    "const_brightness" : 0
                },
                {
                    "bright_time" : "civil_twilight_end",
                    "dark_time" : "23:59:59",
                    "const_brightness" : 100
                }
            ]
        }
    ]
    light = SmartYeelight(debug = True)
    light.deploy_policy(light_policy)
    light.start()
    while light.is_running():
        try:
            sleep(99999)
        except:
            light.stop()

